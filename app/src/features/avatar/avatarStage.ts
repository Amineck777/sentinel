// three.js + three-vrm でアバターを描く「舞台」。React からは命令(load / setEmotion / speak)だけ呼ぶ。
// 描画ループ・瞬き・口パク・表情の切り替えはここで毎フレーム合成する(ADR 0109)。
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { VRM, VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
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

/** 0→1 に滑らかに近づける。dt に依存させてフレームレートが変わっても速さを揃える */
function approach(current: number, target: number, speed: number, dt: number): number {
  return current + (target - current) * (1 - Math.exp(-speed * dt));
}

export class AvatarStage {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly controls: OrbitControls;
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

  // 口パク(文字から)
  private timeline: Segment[] = [];
  private speakStartedAt = -1;
  // 口パク(音量から)
  private analyser: AnalyserNode | null = null;
  private analyserBuf: Float32Array<ArrayBuffer> | null = null;

  constructor(private readonly canvas: HTMLCanvasElement) {
    // alpha: true で背景を透明にしておく(後で透明・枠なしの Tauri 窓に載せるため)
    this.renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.camera = new THREE.PerspectiveCamera(30, 1, 0.1, 20);
    this.camera.position.set(0, 1.35, 1.6);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.target.set(0, 1.3, 0);
    this.controls.update();

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
    if (vrm.lookAt) vrm.lookAt.target = this.camera;
    this.current.clear();

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

  /** 文字列から口パクを再生する。戻り値は再生にかかる秒数 */
  speak(text: string, moraSec?: number): number {
    this.stopAudio();
    this.timeline = buildTimeline(textToVisemes(text), moraSec);
    this.speakStartedAt = this.elapsed;
    return timelineDuration(this.timeline);
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
    this.controls.dispose();
    if (this.vrm) VRMUtils.deepDispose(this.vrm.scene);
    this.renderer.dispose();
  }

  /** Tポーズのままだと不自然なので、腕を下ろした休めの姿勢にする */
  private restPose(vrm: VRM): void {
    const h = vrm.humanoid;
    h.getNormalizedBoneNode("leftUpperArm")?.rotation.set(0, 0, 1.2);
    h.getNormalizedBoneNode("rightUpperArm")?.rotation.set(0, 0, -1.2);
    h.getNormalizedBoneNode("leftLowerArm")?.rotation.set(0, 0.2, 0);
    h.getNormalizedBoneNode("rightLowerArm")?.rotation.set(0, -0.2, 0);
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
    this.elapsed += dt;
    if (this.vrm) this.animate(this.vrm, dt);
    this.renderer.render(this.scene, this.camera);
  };

  private animate(vrm: VRM, dt: number): void {
    const em = vrm.expressionManager;
    if (em) {
      const targets = new Map<string, number>();
      // 1) 感情
      for (const e of EMOTIONS) {
        if (e !== "neutral") targets.set(e, e === this.emotion ? this.emotionWeight : 0);
      }
      // 2) 瞬き
      targets.set("blink", this.blinkWeight());
      // 3) 口
      const mouth = this.mouthWeights();
      for (const v of VOWELS) targets.set(v, mouth[v]);

      for (const [preset, target] of targets) {
        const name = this.resolveExpression(vrm, preset);
        if (!name) continue;
        // 口は速く、感情はゆっくり切り替える
        const speed = preset === "blink" ? 60 : VOWELS.includes(preset as Vowel) ? 25 : 8;
        const value = approach(this.current.get(name) ?? 0, target, speed, dt);
        this.current.set(name, value);
        em.setValue(name, value);
      }
    }

    // 呼吸:胸を少しだけ上下させる
    const chest = vrm.humanoid.getNormalizedBoneNode("chest");
    if (chest) chest.rotation.x = Math.sin(this.elapsed * 1.6) * 0.015;

    vrm.update(dt);
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
      this.nextBlinkAt = t + 2 + Math.random() * 4; // 2〜6 秒おき
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
