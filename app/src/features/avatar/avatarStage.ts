// three.js + three-vrm でアバターを描く「舞台」。React からは命令(load / setEmotion / speak / setState)だけ呼ぶ。
// 描画ループ・瞬き・口パク・表情・状態ごとの仕草はここで毎フレーム合成する(ADR 0109 / 0114)。
//
// 動きは「いつも重ねる層」と「状態ごとの層」の足し算(学習ノート 07):
//   いつも: 呼吸・体の揺れ・ランダムなまばたき・視線(マウスを目で追う)
//   状態:   聞いている=少し前のめりでときどきうなずく / 考え中=首をかしげて斜め上を見る /
//           話し中=文の切れ目でうなずく / 居眠り=あくびの後に目を閉じてうつむく / 困り=うつむいて悲しげ
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { VRM, VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
import type { AvatarState } from "./cueChannel";
import {
  VOWELS,
  buildTimeline,
  sampleTimeline,
  textToVisemes,
  timelineDuration,
  type Segment,
  type Vowel,
} from "./lipsync";

/** 感情の表情。VRM 1.0 のプリセット名(VRM 0.x のモデルも three-vrm がこの名前に読み替える) */
export const EMOTIONS = ["neutral", "happy", "angry", "sad", "relaxed", "surprised"] as const;
export type Emotion = (typeof EMOTIONS)[number];

export interface ModelInfo {
  title: string;
  author: string;
  specVersion: "0.x" | "1.0";
  expressions: string[];
}

/** 状態ごとの描画の頻度(fps)。待機中や居眠り中は GPU を休ませる(8GB の VRAM で LLM と同居するため) */
const FPS: Record<AvatarState, number> = {
  idle: 30,
  listening: 60,
  thinking: 30,
  speaking: 60,
  sleeping: 10,
  error: 15,
};

/** 状態ごとの頭・背骨の傾き(ラジアン)。x=うなずく向き(+で下を向く) z=首をかしげる */
const POSE: Record<AvatarState, { headX: number; headZ: number; spineX: number }> = {
  idle: { headX: 0, headZ: 0, spineX: 0 },
  listening: { headX: 0.04, headZ: 0.03, spineX: 0.04 },
  thinking: { headX: -0.08, headZ: 0.13, spineX: 0 },
  speaking: { headX: 0, headZ: 0, spineX: 0.02 },
  sleeping: { headX: 0.32, headZ: 0.1, spineX: 0.06 },
  error: { headX: 0.14, headZ: -0.04, spineX: 0.03 },
};

/** 0→1 に滑らかに近づける。dt に依存させてフレームレートが変わっても速さを揃える */
function approach(current: number, target: number, speed: number, dt: number): number {
  return current + (target - current) * (1 - Math.exp(-speed * dt));
}

export class AvatarStage {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly controls: OrbitControls | null;
  private lastTime = performance.now();
  private readonly resizeObserver: ResizeObserver;
  private vrm: VRM | null = null;
  private frame = 0;
  private elapsed = 0;

  // 表情
  private emotion: Emotion = "neutral";
  private emotionWeight = 1;
  private readonly current = new Map<string, number>();

  // 瞬き
  blinkEnabled = true;
  private nextBlinkAt = 2;
  private blinkStartedAt = -1;
  private doubleBlink = false;

  // 状態と仕草
  private state: AvatarState = "idle";
  private stateSince = 0;
  private readonly pose = { headX: 0, headZ: 0, spineX: 0, yaw: 0, pitch: 0 };
  private nodStartedAt = -1;
  private nextListenNodAt = 0;
  private glanceUntil = -1;
  private glanceDir = 1;
  private nextGlanceAt = 25;

  // 視線: マウスカーソル(キャンバス上の割合。-1〜1、外なら絶対値が 1 を超える)
  followCursor = true;
  private cursor: { x: number; y: number } | null = null;
  private readonly gaze = new THREE.Object3D();
  private readonly gazeNdc = new THREE.Vector2();

  // クリック透過のための当たり判定(描いた直後の 1 画素の不透明度を読む)
  private probe: { x: number; y: number } | null = null;
  private probeHit = false;
  private sinceRender = 1;

  // 口パク(文字から)
  private timeline: Segment[] = [];
  private speakStartedAt = -1;
  // 口パク(音量から)
  private analyser: AnalyserNode | null = null;
  private analyserBuf: Float32Array<ArrayBuffer> | null = null;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    options: { orbit?: boolean } = {},
  ) {
    // alpha: true で背景を透明にしておく(後で透明・枠なしの Tauri 窓に載せるため)
    this.renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.camera = new THREE.PerspectiveCamera(30, 1, 0.1, 20);
    this.camera.position.set(0, 1.35, 1.6);
    const target = new THREE.Vector3(0, 1.3, 0);
    this.camera.lookAt(target);
    // ドラッグで回す・ホイールで寄る。デスクトップ表示ではドラッグを窓の移動に使うので付けない
    this.controls = options.orbit === false ? null : new OrbitControls(this.camera, canvas);
    if (this.controls) {
      this.controls.target.copy(target);
      this.controls.update();
    }

    this.scene.add(this.gaze);

    const light = new THREE.DirectionalLight(0xffffff, Math.PI);
    light.position.set(1, 1, 1).normalize();
    this.scene.add(light, new THREE.AmbientLight(0xffffff, 0.4));

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    this.resize();
    this.loop();
  }

  async load(url: string): Promise<ModelInfo> {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await loader.loadAsync(url);
    const vrm = gltf.userData.vrm as VRM | undefined;
    if (!vrm) throw new Error("VRM ではありません(glTF に VRM 拡張がない)");

    // 描画を軽くする定番の後処理
    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    VRMUtils.combineSkeletons(gltf.scene);
    // VRM 0.x は向きが逆(-Z 向き)なので、1.0 と同じ向きに回す。1.0 なら何もしない
    VRMUtils.rotateVRM0(vrm);
    vrm.scene.traverse((o) => (o.frustumCulled = false));

    if (this.vrm) {
      this.scene.remove(this.vrm.scene);
      VRMUtils.deepDispose(this.vrm.scene);
    }
    this.vrm = vrm;
    this.scene.add(vrm.scene);
    this.restPose(vrm);
    if (vrm.lookAt) vrm.lookAt.target = this.gaze;
    this.current.clear();
    this.frameModel(vrm);

    const meta = vrm.meta;
    const is0 = meta.metaVersion === "0";
    return {
      title: (is0 ? meta.title : meta.name) ?? "(無題)",
      author: (is0 ? meta.author : meta.authors?.join(", ")) ?? "(不明)",
      specVersion: is0 ? "0.x" : "1.0",
      expressions: vrm.expressionManager?.expressions.map((e) => e.expressionName) ?? [],
    };
  }

  setEmotion(emotion: Emotion, weight = 1): void {
    this.emotion = emotion;
    this.emotionWeight = weight;
  }

  /** 状態を変える。仕草はここから滑らかに移る */
  setState(state: AvatarState): void {
    if (state === this.state) return;
    this.state = state;
    this.stateSince = this.elapsed;
    if (state === "listening") this.nextListenNodAt = this.elapsed + 1.5;
  }

  /** 小さくうなずく(送信した瞬間・文の切れ目) */
  nod(): void {
    this.nodStartedAt = this.elapsed;
  }

  /** マウスカーソルの位置(キャンバス左上からの CSS ピクセル)。null なら正面を見る */
  setCursor(pos: { x: number; y: number } | null): void {
    if (!pos) {
      this.cursor = null;
      return;
    }
    const w = this.canvas.clientWidth || 1;
    const h = this.canvas.clientHeight || 1;
    this.cursor = { x: (pos.x / w) * 2 - 1, y: 1 - (pos.y / h) * 2 };
  }

  /**
   * その位置に体が描かれているか(クリック透過の判定)。直前に描いたフレームの結果を返すので、
   * 呼ぶたびに位置を覚えておき、次のフレームで読む(数十ミリ秒の遅れは気にならない)
   */
  hitTest(x: number, y: number): boolean {
    this.probe = { x, y };
    return this.probeHit;
  }

  /** 文字列から口パクを再生する。戻り値は再生にかかる秒数 */
  speak(text: string, moraSec?: number): number {
    this.stopAudio();
    this.timeline = buildTimeline(textToVisemes(text), moraSec);
    this.speakStartedAt = this.elapsed;
    return timelineDuration(this.timeline);
  }

  /** 時刻つきの口の並びをいまから再生する(声と一緒に。TTS が作ったタイムラインを渡す) */
  speakTimeline(timeline: Segment[]): void {
    this.stopAudio();
    this.timeline = timeline;
    this.speakStartedAt = this.elapsed;
  }

  /** 口パクを止めて口を閉じる */
  stopSpeaking(): void {
    this.timeline = [];
  }

  /** 音声要素の音量で口を動かす(声の中身は見ずに「大きさ → 口の開き」だけ) */
  attachAudio(analyser: AnalyserNode | null): void {
    this.timeline = [];
    this.analyser = analyser;
    this.analyserBuf = analyser ? new Float32Array(analyser.fftSize) : null;
  }

  private stopAudio(): void {
    this.analyser = null;
    this.analyserBuf = null;
  }

  dispose(): void {
    cancelAnimationFrame(this.frame);
    this.resizeObserver.disconnect();
    this.controls?.dispose();
    if (this.vrm) VRMUtils.deepDispose(this.vrm.scene);
    this.renderer.dispose();
  }

  /** Tポーズのままだと不自然なので、腕を下ろした休めの姿勢にする */
  private restPose(vrm: VRM): void {
    const h = vrm.humanoid;
    h.getNormalizedBoneNode("leftUpperArm")?.rotation.set(0, 0, -1.2);
    h.getNormalizedBoneNode("rightUpperArm")?.rotation.set(0, 0, 1.2);
    h.getNormalizedBoneNode("leftLowerArm")?.rotation.set(0, 0.2, 0);
    h.getNormalizedBoneNode("rightLowerArm")?.rotation.set(0, -0.2, 0);
  }

  /**
   * 頭が窓の上から 4 割ほどの所に来るよう、カメラを合わせる。上の余白は吹き出しのため。
   * モデルごとに身長が違うので、頭の骨の高さから決める
   */
  private frameModel(vrm: VRM): void {
    vrm.scene.updateMatrixWorld(true);
    const head = vrm.humanoid.getNormalizedBoneNode("head");
    const headY = head ? head.getWorldPosition(new THREE.Vector3()).y : 1.4;
    const half = Math.max(0.45, headY * 0.38); // 画面の縦の半分に映す高さ(m)
    const centerY = headY - 0.15 * half;
    const dist = half / Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    this.camera.position.set(0, centerY, dist);
    const target = new THREE.Vector3(0, centerY, 0);
    this.camera.lookAt(target);
    if (this.controls) {
      this.controls.target.copy(target);
      this.controls.update();
    }
  }

  private resize(): void {
    const w = this.canvas.clientWidth || 1;
    const h = this.canvas.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  private loop = (): void => {
    this.frame = requestAnimationFrame(this.loop);
    const now = performance.now();
    const dt = Math.min((now - this.lastTime) / 1000, 0.1);
    this.lastTime = now;
    // 窓が隠れているときは描かない。状態ごとの fps より速くは描かない
    this.sinceRender += dt;
    if (document.hidden || this.sinceRender < 1 / FPS[this.state] - 0.004) return;
    const step = Math.min(this.sinceRender, 0.1);
    this.sinceRender = 0;
    this.elapsed += step;
    if (this.vrm) this.animate(this.vrm, step);
    this.renderer.render(this.scene, this.camera);
    this.readProbe();
  };

  private readonly pixel = new Uint8Array(4);
  private readProbe(): void {
    if (!this.probe) return;
    const gl = this.renderer.getContext();
    const dpr = this.renderer.getPixelRatio();
    const x = Math.floor(this.probe.x * dpr);
    const y = Math.floor(gl.drawingBufferHeight - this.probe.y * dpr);
    if (x < 0 || y < 0 || x >= gl.drawingBufferWidth || y >= gl.drawingBufferHeight) {
      this.probeHit = false;
    } else {
      // 描いた直後なら preserveDrawingBuffer なしでも読める
      gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, this.pixel);
      this.probeHit = this.pixel[3] > 24;
    }
  }

  private animate(vrm: VRM, dt: number): void {
    const t = this.elapsed;
    const sinceState = t - this.stateSince;
    const sleeping = this.state === "sleeping";
    // 居眠りの入り: 最初の 2.4 秒はあくび(口を開けて目を細める)、その後は目を閉じる
    const yawn = sleeping && sinceState < 2.4 ? Math.sin((Math.PI * sinceState) / 2.4) : 0;

    const em = vrm.expressionManager;
    if (em) {
      const targets = new Map<string, number>();
      // 1) 感情(困りのときは控えめに悲しげ)
      const emotion = this.state === "error" ? "sad" : this.emotion;
      const weight = this.state === "error" ? 0.35 : this.emotionWeight;
      for (const e of EMOTIONS) {
        if (e !== "neutral") targets.set(e, e === emotion ? weight : 0);
      }
      // 2) 瞬き(居眠り中は閉じたまま)
      const eyes = sleeping ? (sinceState < 2.4 ? 0.55 * yawn : 1) : this.blinkWeight();
      targets.set("blink", eyes);
      // 3) 口
      const mouth = this.mouthWeights();
      if (yawn > 0) mouth.aa = Math.max(mouth.aa, 0.7 * yawn);
      for (const v of VOWELS) targets.set(v, mouth[v]);

      for (const [preset, target] of targets) {
        const name = this.resolveExpression(vrm, preset);
        if (!name) continue;
        // 口は速く、感情はゆっくり切り替える。居眠りの目はゆっくり閉じる
        const speed =
          preset === "blink" ? (sleeping ? 3 : 60) : VOWELS.includes(preset as Vowel) ? 25 : 8;
        const value = approach(this.current.get(name) ?? 0, target, speed, dt);
        this.current.set(name, value);
        em.setValue(name, value);
      }
    }

    this.updatePose(vrm, dt);
    this.updateGaze(dt);
    vrm.update(dt);
  }

  /** 呼吸・揺れ・状態ごとの頭の傾き・うなずき */
  private updatePose(vrm: VRM, dt: number): void {
    const t = this.elapsed;
    const h = vrm.humanoid;
    const goal = POSE[this.state];
    const p = this.pose;
    p.headX = approach(p.headX, goal.headX, 3, dt);
    p.headZ = approach(p.headZ, goal.headZ, 3, dt);
    p.spineX = approach(p.spineX, goal.spineX, 3, dt);

    // 聞いている間はときどき小さくうなずく
    if (this.state === "listening" && t >= this.nextListenNodAt) {
      this.nod();
      this.nextListenNodAt = t + 3 + Math.random() * 3;
    }
    let nod = 0;
    if (this.nodStartedAt >= 0) {
      const q = (t - this.nodStartedAt) / 0.5;
      if (q >= 1) this.nodStartedAt = -1;
      else nod = 0.11 * Math.sin(Math.PI * q);
    }

    // 呼吸(居眠り中はゆっくり深く)と、呼吸とずらした周期の体の揺れ
    const sleeping = this.state === "sleeping";
    const breath = Math.sin(t * (sleeping ? 0.9 : 1.6)) * (sleeping ? 0.025 : 0.015);
    const sway = Math.sin(t * 0.83) * 0.018 + Math.sin(t * 0.37) * 0.008;

    const chest = h.getNormalizedBoneNode("chest");
    if (chest) chest.rotation.x = breath;
    const spine = h.getNormalizedBoneNode("spine");
    if (spine) spine.rotation.set(p.spineX, 0, sway);
    const head = h.getNormalizedBoneNode("head");
    // 頭は目より少し遅れて、少しだけ視線の方へ向く(追いすぎない)
    if (head) head.rotation.set(p.headX + nod + p.pitch, p.yaw, p.headZ - sway * 0.5);
  }

  /** 目の向き。マウスを追う・考え中は斜め上・ときどきよそ見 */
  private updateGaze(dt: number): void {
    const t = this.elapsed;
    const target = this.gazeNdc;
    if (this.state === "thinking") {
      target.set(-0.7, 0.8);
    } else if (this.state === "sleeping" || this.state === "error") {
      target.set(0, -0.6);
    } else {
      // 待機中は 20〜60 秒に 1 回、2 秒ほどよそ見する(窓の外を見るような仕草)
      if (this.state === "idle" && t >= this.nextGlanceAt) {
        this.glanceUntil = t + 2;
        this.glanceDir = Math.random() < 0.5 ? -1 : 1;
        this.nextGlanceAt = t + 20 + Math.random() * 40;
      }
      if (t < this.glanceUntil) target.set(0.9 * this.glanceDir, 0.1);
      else if (this.followCursor && this.cursor && this.state !== "listening")
        target.set(
          THREE.MathUtils.clamp(this.cursor.x, -1.6, 1.6),
          THREE.MathUtils.clamp(this.cursor.y, -1.6, 1.6),
        );
      else target.set(0, 0); // 聞いている間はこちら(カメラ)を見る
    }
    const p = this.pose;
    p.yaw = approach(p.yaw, target.x * 0.12, 2.5, dt);
    p.pitch = approach(p.pitch, -target.y * 0.07, 2.5, dt);
    // 視線の先: カメラの位置から、カーソルの方向へ少しずらした点
    const goal = this.camera.position.clone();
    goal.x += target.x * 0.45;
    goal.y += target.y * 0.35;
    this.gaze.position.lerp(goal, 1 - Math.exp(-10 * dt));
  }

  /**
   * プリセット名の表情がモデルに無いとき、同名の独自表情(先頭大文字など)で代用する。
   * 例: VRM 0.x には「おどろき」のプリセットが無く、モデル作者が "Surprised" を独自に足していることがある。
   */
  private resolveExpression(vrm: VRM, preset: string): string | null {
    const em = vrm.expressionManager;
    if (!em) return null;
    if (em.getExpression(preset)) return preset;
    const alt = preset[0].toUpperCase() + preset.slice(1);
    return em.getExpression(alt) ? alt : null;
  }

  private blinkWeight(): number {
    if (!this.blinkEnabled) return 0;
    const t = this.elapsed;
    if (this.blinkStartedAt < 0 && t >= this.nextBlinkAt) {
      this.blinkStartedAt = t;
    }
    if (this.blinkStartedAt < 0) return 0;
    const p = (t - this.blinkStartedAt) / 0.15; // 0.15 秒で閉じて開く
    if (p >= 1) {
      this.blinkStartedAt = -1;
      // 3〜6 秒おき。ときどき 2 回続けてまばたきする(一定間隔だと機械っぽく見える)
      this.doubleBlink = !this.doubleBlink && Math.random() < 0.2;
      this.nextBlinkAt = t + (this.doubleBlink ? 0.12 : 3 + Math.random() * 3);
      return 0;
    }
    return Math.sin(Math.PI * p);
  }

  private mouthWeights(): Record<Vowel, number> {
    if (this.analyser && this.analyserBuf) {
      this.analyser.getFloatTimeDomainData(this.analyserBuf);
      let sum = 0;
      for (const x of this.analyserBuf) sum += x * x;
      const rms = Math.sqrt(sum / this.analyserBuf.length);
      // 声の大きさ(RMS)0.02〜0.2 を口の開き 0〜1 に。母音は分からないので「あ」で代用
      const open = Math.min(1, Math.max(0, (rms - 0.02) / 0.18));
      return { aa: open, ih: 0, ou: 0, ee: 0, oh: 0 };
    }
    if (this.timeline.length > 0) {
      const t = this.elapsed - this.speakStartedAt;
      if (t > timelineDuration(this.timeline)) this.timeline = [];
      return sampleTimeline(this.timeline, t);
    }
    return { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
  }
}
