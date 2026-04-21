<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as THREE from "three";
import { GLTFLoader, type GLTFParser } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRM, VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
import type { AvatarBridgeState } from "../../../virtual/bridge";
import { CODE_AGENT_AVATAR_HOST_READY_EVENT } from "../../../virtual/protocol";
import type { AvatarConfig } from "../../types";

const props = defineProps<{
  avatar: AvatarConfig;
  status: string;
  latestAgentMessage: string;
  isStreaming: boolean;
  avatarState: AvatarBridgeState;
  interactionMode: boolean;
}>();

const runtimeHostRef = ref<HTMLDivElement | null>(null);
const sceneHostRef = ref<HTMLDivElement | null>(null);
const stageSurfaceRef = ref<HTMLDivElement | null>(null);
const sceneMode = ref<"vrm" | "fallback" | "loading" | "error">("fallback");
const isDragReady = ref(false);
const isDragging = ref(false);

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let resizeObserver: ResizeObserver | null = null;
let animationFrame = 0;
let loadGeneration = 0;
let clock = new THREE.Clock();
let currentVrm: VRM | null = null;
let currentVrmGroup: THREE.Group | null = null;
let modelCenter = new THREE.Vector3(0, 1, 0);
let modelSize = new THREE.Vector3(1, 2, 1);
let greetingPlayed = false;
let greetingSpeaking = false;
let nextBlinkAt = 0;
let blinkStartedAt = 0;
let holdTimer: number | null = null;
let draggingPointerId: number | null = null;
let pointerDownX = 0;
let pointerDownY = 0;
let lastPointerX = 0;
let lastPointerY = 0;
let manualYaw = 0;
let manualLift = 0;

const avatarRaycaster = new THREE.Raycaster();
const avatarPointer = new THREE.Vector2();

interface PoseBoneState {
  node: THREE.Object3D;
  baseRotation: THREE.Euler;
}

interface AvatarPoseRig {
  spine?: PoseBoneState;
  chest?: PoseBoneState;
  neck?: PoseBoneState;
  head?: PoseBoneState;
  leftUpperArm?: PoseBoneState;
  rightUpperArm?: PoseBoneState;
  leftLowerArm?: PoseBoneState;
  rightLowerArm?: PoseBoneState;
  leftHand?: PoseBoneState;
  rightHand?: PoseBoneState;
}

let poseRig: AvatarPoseRig | null = null;

onMounted(() => {
  ensureResizeObserver();
  notifyHostReady();
  void mountStage();
});

watch(
  () => [props.avatar.mode, props.avatar.vrmUri],
  () => {
    void mountStage();
  },
);

onBeforeUnmount(() => {
  loadGeneration += 1;
  stopGreetingSpeech();
  clearInteractionState();
  disposeStage();
  resizeObserver?.disconnect();
  resizeObserver = null;
});

/**
 * 按当前头像资源重新挂载舞台。
 */
async function mountStage(): Promise<void> {
  const host = sceneHostRef.value;
  const nextGeneration = ++loadGeneration;

  disposeStage();

  if (!host) {
    return;
  }

  notifyHostReady();
  resetInteraction();

  if (!props.avatar.vrmUri || props.avatar.mode === "prototype") {
    sceneMode.value = "fallback";
    return;
  }

  sceneMode.value = "loading";

  renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(0x000000, 0);
  renderer.domElement.classList.add("vrm-stage-canvas");

  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(40, 1, 0.1, 40);

  host.replaceChildren(renderer.domElement);
  installLights(scene);
  resizeRenderer();

  try {
    const loader = new GLTFLoader();
    loader.register((parser: GLTFParser) => new VRMLoaderPlugin(parser));

    const vrmBundle = await loadVrmScene(loader, props.avatar.vrmUri, scene);
    if (nextGeneration !== loadGeneration || !scene || !camera || !renderer) {
      return;
    }

    currentVrm = vrmBundle.vrm;
    currentVrmGroup = vrmBundle.group;
    modelCenter = vrmBundle.center;
    modelSize = vrmBundle.size;
    poseRig = createNaturalPoseRig(vrmBundle.vrm);
    resetBlinkSchedule();
    fitCameraToModel(vrmBundle.size, vrmBundle.cameraOffset);

    clock = new THREE.Clock();
    sceneMode.value = "vrm";
    playGreeting(false);
    startAnimationLoop();
  } catch (error) {
    sceneMode.value = "fallback";
    console.error("[Code Agent] Failed to load VRM scene.", error);
    disposeStage();
  }
}

/**
 * 监听舞台尺寸变化并同步渲染器大小。
 */
function ensureResizeObserver(): void {
  if (resizeObserver || !sceneHostRef.value) {
    return;
  }

  resizeObserver = new ResizeObserver(() => {
    resizeRenderer();
  });
  resizeObserver.observe(sceneHostRef.value);
}

/**
 * 通知 AIRI 兼容桥当前宿主节点已就绪。
 */
function notifyHostReady(): void {
  if (!runtimeHostRef.value) {
    return;
  }

  window.dispatchEvent(
    new CustomEvent(CODE_AGENT_AVATAR_HOST_READY_EVENT, {
      detail: { hostId: props.avatarState.runtimeHostId },
    }),
  );
}

/**
 * 为模型补充基础灯光。
 */
function installLights(targetScene: THREE.Scene): void {
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.92);
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.15);
  const rimLight = new THREE.DirectionalLight(0x9edfff, 0.78);
  const fillLight = new THREE.DirectionalLight(0xffd7a8, 0.42);

  keyLight.position.set(1.45, 2.05, 2.35);
  rimLight.position.set(-2.3, 1.75, -2.1);
  fillLight.position.set(-1.05, 0.85, 1.25);

  targetScene.add(ambientLight, keyLight, rimLight, fillLight);
}

/**
 * 根据模型尺寸调整镜头，优先显示头部和上半身。
 */
function fitCameraToModel(size: THREE.Vector3, initialOffset: THREE.Vector3): void {
  if (!camera) {
    return;
  }

  const lookAtTarget = modelCenter.clone();
  lookAtTarget.y += size.y * 0.12;

  const cameraOffset = initialOffset.clone();
  cameraOffset.y += size.y * 0.16;
  cameraOffset.z *= 1.28;

  camera.position.copy(modelCenter).add(cameraOffset);
  camera.lookAt(lookAtTarget);
  camera.updateProjectionMatrix();
}

/**
 * 启动逐帧渲染与轻量待机动画。
 */
function startAnimationLoop(): void {
  stopAnimationLoop();

  const renderFrame = () => {
    if (!renderer || !scene || !camera) {
      return;
    }

    const delta = clock.getDelta();
    const elapsed = clock.getElapsedTime();

    if (currentVrm) {
      currentVrm.update(delta);
      currentVrm.materials?.forEach((material) => {
        const updatableMaterial = material as THREE.Material & { update?: (frameDelta: number) => void };
        updatableMaterial.update?.(delta);
      });
      applyAnimatedPose(elapsed);
      applyExpressionState(elapsed);
    }

    if (currentVrmGroup) {
      const idleYaw = isDragging.value ? 0 : Math.sin(elapsed * 0.3) * 0.08;
      const idleLift = isDragging.value ? 0 : Math.sin(elapsed * 1.1) * 0.015;
      currentVrmGroup.rotation.y = manualYaw + idleYaw;
      currentVrmGroup.position.y = manualLift + idleLift;
    }

    camera.position.x = modelCenter.x + (isDragging.value ? 0 : Math.sin(elapsed * 0.18) * 0.04);
    camera.lookAt(
      new THREE.Vector3(
        modelCenter.x,
        modelCenter.y + modelSize.y * 0.09 + manualLift * 0.32,
        modelCenter.z,
      ),
    );

    renderer.render(scene, camera);
    animationFrame = window.requestAnimationFrame(renderFrame);
  };

  animationFrame = window.requestAnimationFrame(renderFrame);
}

/**
 * 停止渲染循环。
 */
function stopAnimationLoop(): void {
  if (!animationFrame) {
    return;
  }

  window.cancelAnimationFrame(animationFrame);
  animationFrame = 0;
}

/**
 * 让渲染器跟随容器尺寸变化。
 */
function resizeRenderer(): void {
  if (!renderer || !camera || !sceneHostRef.value) {
    return;
  }

  const width = Math.max(sceneHostRef.value.clientWidth, 1);
  const height = Math.max(sceneHostRef.value.clientHeight, 1);

  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

/**
 * 释放当前舞台资源。
 */
function disposeStage(): void {
  stopAnimationLoop();

  if (sceneHostRef.value) {
    sceneHostRef.value.replaceChildren();
  }

  currentVrm = null;
  currentVrmGroup = null;
  poseRig = null;
  scene = null;
  camera = null;

  if (renderer) {
    renderer.dispose();
    renderer = null;
  }
}

/**
 * 为默认 T Pose 追加更自然的待机姿态。
 */
function createNaturalPoseRig(vrm: VRM): AvatarPoseRig {
  const humanoid = vrm.humanoid;
  if (!humanoid) {
    return {};
  }

  return {
    spine: offsetBoneRotation(humanoid, "spine", 0.05, 0, 0),
    chest: offsetBoneRotation(humanoid, "chest", 0.04, 0, 0),
    neck: offsetBoneRotation(humanoid, "neck", -0.02, 0, 0),
    head: offsetBoneRotation(humanoid, "head", 0.02, 0, 0),
    leftUpperArm: offsetBoneRotation(humanoid, "leftUpperArm", 0.14, 0.04, 1.04),
    rightUpperArm: offsetBoneRotation(humanoid, "rightUpperArm", 0.14, -0.04, -1.04),
    leftLowerArm: offsetBoneRotation(humanoid, "leftLowerArm", 0.06, 0.02, 0.16),
    rightLowerArm: offsetBoneRotation(humanoid, "rightLowerArm", 0.06, -0.02, -0.16),
    leftHand: offsetBoneRotation(humanoid, "leftHand", 0.04, 0, 0.1),
    rightHand: offsetBoneRotation(humanoid, "rightHand", 0.04, 0, -0.1),
  };
}

/**
 * 对单个标准化骨骼追加旋转偏移，并保存当前基础值。
 */
function offsetBoneRotation(
  humanoid: VRM["humanoid"],
  boneName: string,
  x: number,
  y: number,
  z: number,
): PoseBoneState | undefined {
  const node = humanoid.getNormalizedBoneNode(boneName as never);
  if (!node) {
    return undefined;
  }

  node.rotation.x += x;
  node.rotation.y += y;
  node.rotation.z += z;

  return {
    node,
    baseRotation: node.rotation.clone(),
  };
}

/**
 * 在基础姿态之上叠加轻量呼吸、点头和手臂摆动。
 */
function applyAnimatedPose(elapsed: number): void {
  if (!poseRig) {
    return;
  }

  const breathing = Math.sin(elapsed * 1.2);
  const sway = Math.sin(elapsed * 0.55);
  const nod = Math.sin(elapsed * 0.9);

  animateBone(poseRig.spine, { x: breathing * 0.012, z: sway * 0.018 });
  animateBone(poseRig.chest, { x: breathing * 0.018, z: sway * 0.024 });
  animateBone(poseRig.neck, { x: nod * 0.012, y: sway * 0.025 });
  animateBone(poseRig.head, { x: nod * 0.018, y: sway * 0.045 });
  animateBone(poseRig.leftUpperArm, { x: breathing * 0.015, z: breathing * 0.03 });
  animateBone(poseRig.rightUpperArm, { x: breathing * 0.015, z: -breathing * 0.03 });
  animateBone(poseRig.leftLowerArm, { z: breathing * 0.016 });
  animateBone(poseRig.rightLowerArm, { z: -breathing * 0.016 });
  animateBone(poseRig.leftHand, { z: sway * 0.02 });
  animateBone(poseRig.rightHand, { z: -sway * 0.02 });
}

/**
 * 在骨骼基础姿态上叠加动态偏移。
 */
function animateBone(
  state: PoseBoneState | undefined,
  offsets: Partial<Record<"x" | "y" | "z", number>>,
): void {
  if (!state) {
    return;
  }

  state.node.rotation.x = state.baseRotation.x + (offsets.x ?? 0);
  state.node.rotation.y = state.baseRotation.y + (offsets.y ?? 0);
  state.node.rotation.z = state.baseRotation.z + (offsets.z ?? 0);
}

/**
 * 根据当前状态驱动表情、眨眼和简化口型。
 */
function applyExpressionState(elapsed: number): void {
  const manager = currentVrm?.expressionManager;
  if (!manager) {
    return;
  }

  const speaking = props.isStreaming || greetingSpeaking;
  const blink = computeBlinkWeight();
  const speakingWeight = speaking ? 0.16 + (Math.sin(elapsed * 15) * 0.5 + 0.5) * 0.28 : 0;
  const happyWeight = speaking ? 0.18 : 0.1;
  const relaxedWeight = props.status.includes("思考") ? 0.22 : 0.08;

  manager.resetValues();
  setExpressionWeight("blink", blink);
  setExpressionWeight("blinkLeft", blink * 0.9);
  setExpressionWeight("blinkRight", blink * 0.9);
  setExpressionWeight("happy", happyWeight);
  setExpressionWeight("relaxed", relaxedWeight);

  if (speakingWeight > 0) {
    setExpressionWeight("aa", speakingWeight);
    setExpressionWeight("ih", speakingWeight * 0.34);
    setExpressionWeight("ou", speakingWeight * 0.18);
  }

  manager.update();
}

/**
 * 仅在表达预设存在时写入权重。
 */
function setExpressionWeight(name: string, weight: number): void {
  const manager = currentVrm?.expressionManager;
  if (!manager || !manager.getExpression(name)) {
    return;
  }

  manager.setValue(name, Math.max(0, Math.min(1, weight)));
}

/**
 * 计算眨眼权重。
 */
function computeBlinkWeight(): number {
  const now = performance.now();
  if (!nextBlinkAt) {
    resetBlinkSchedule();
  }

  if (!blinkStartedAt && now >= nextBlinkAt) {
    blinkStartedAt = now;
  }

  if (!blinkStartedAt) {
    return 0;
  }

  const progress = (now - blinkStartedAt) / 160;
  if (progress >= 1) {
    blinkStartedAt = 0;
    resetBlinkSchedule();
    return 0;
  }

  return progress < 0.5 ? progress * 2 : (1 - progress) * 2;
}

/**
 * 重置下一次眨眼的随机时间点。
 */
function resetBlinkSchedule(): void {
  nextBlinkAt = performance.now() + 1400 + Math.random() * 2400;
}

/**
 * 播放欢迎语。
 */
function playGreeting(force: boolean): void {
  if ((!force && greetingPlayed) || typeof window === "undefined" || !("speechSynthesis" in window)) {
    return;
  }

  if (!force) {
    greetingPlayed = true;
  }

  const utterance = new SpeechSynthesisUtterance("你好，我是 Code Agent，很高兴见到你。");
  utterance.lang = "zh-CN";
  utterance.rate = 1.02;
  utterance.pitch = 1.04;

  const chineseVoice = window.speechSynthesis
    .getVoices()
    .find((voice) => /zh|cmn/i.test(voice.lang) || /中文|Chinese/i.test(voice.name));

  if (chineseVoice) {
    utterance.voice = chineseVoice;
  }

  utterance.onstart = () => {
    greetingSpeaking = true;
  };
  utterance.onend = () => {
    greetingSpeaking = false;
  };
  utterance.onerror = () => {
    greetingSpeaking = false;
  };

  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

/**
 * 停止欢迎语播报。
 */
function stopGreetingSpeech(): void {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) {
    return;
  }

  greetingSpeaking = false;
  window.speechSynthesis.cancel();
}

/**
 * 检查当前鼠标是否命中数字人网格。
 */
function isPointerOnAvatar(clientX: number, clientY: number): boolean {
  if (!sceneHostRef.value || !camera || !currentVrmGroup) {
    return false;
  }

  const bounds = sceneHostRef.value.getBoundingClientRect();
  if (!bounds.width || !bounds.height) {
    return false;
  }

  avatarPointer.x = ((clientX - bounds.left) / bounds.width) * 2 - 1;
  avatarPointer.y = -((clientY - bounds.top) / bounds.height) * 2 + 1;
  avatarRaycaster.setFromCamera(avatarPointer, camera);

  return avatarRaycaster.intersectObject(currentVrmGroup, true).some((intersection) => {
    const object = intersection.object as THREE.Object3D & { isMesh?: boolean };
    return Boolean(object.isMesh);
  });
}

/**
 * 长按命中数字人后进入拖拽模式。
 */
function handlePointerDown(event: PointerEvent): void {
  const canStartInteraction = props.interactionMode || isPointerOnAvatar(event.clientX, event.clientY);
  if (event.button !== 0 || sceneMode.value !== "vrm" || !canStartInteraction) {
    return;
  }

  event.preventDefault();
  clearInteractionState();
  draggingPointerId = event.pointerId;
  pointerDownX = event.clientX;
  pointerDownY = event.clientY;
  lastPointerX = event.clientX;
  lastPointerY = event.clientY;

  const activateInteraction = () => {
    if (!stageSurfaceRef.value || draggingPointerId !== event.pointerId) {
      return;
    }

    isDragReady.value = true;
    isDragging.value = true;
    stageSurfaceRef.value.setPointerCapture(event.pointerId);
  };

  if (props.interactionMode) {
    activateInteraction();
    return;
  }

  holdTimer = window.setTimeout(activateInteraction, 180);
}

/**
 * 长按激活后，允许拖拽旋转与抬升数字人。
 */
function handlePointerMove(event: PointerEvent): void {
  if (draggingPointerId === event.pointerId && !isDragging.value) {
    const travel = Math.hypot(event.clientX - pointerDownX, event.clientY - pointerDownY);
    if (travel > 8) {
      clearInteractionState();
      return;
    }
  }

  if (!isDragging.value || draggingPointerId !== event.pointerId) {
    return;
  }

  event.preventDefault();
  const deltaX = event.clientX - lastPointerX;
  const deltaY = event.clientY - lastPointerY;
  lastPointerX = event.clientX;
  lastPointerY = event.clientY;

  manualYaw += deltaX * 0.014;
  manualLift = THREE.MathUtils.clamp(manualLift - deltaY * 0.0105, -2.4, 2.4);
}

/**
 * 结束拖拽交互并释放捕获。
 */
function handlePointerUp(event: PointerEvent): void {
  if (
    stageSurfaceRef.value
    && draggingPointerId === event.pointerId
    && stageSurfaceRef.value.hasPointerCapture(event.pointerId)
  ) {
    stageSurfaceRef.value.releasePointerCapture(event.pointerId);
  }

  clearInteractionState();
}

/**
 * 清理临时拖拽状态。
 */
function clearInteractionState(): void {
  if (holdTimer) {
    clearTimeout(holdTimer);
    holdTimer = null;
  }

  draggingPointerId = null;
  isDragReady.value = false;
  isDragging.value = false;
}

/**
 * 重置视角与手动交互偏移。
 */
function resetInteraction(): void {
  manualYaw = 0;
  manualLift = 0;
  clearInteractionState();
}

/**
 * 对外暴露欢迎语重播入口。
 */
function replayGreeting(): void {
  playGreeting(true);
}

/**
 * 加载 VRM 并计算后续构图所需参数。
 */
function loadVrmScene(
  loader: GLTFLoader,
  url: string,
  targetScene: THREE.Scene,
): Promise<{
  vrm: VRM;
  group: THREE.Group;
  center: THREE.Vector3;
  size: THREE.Vector3;
  cameraOffset: THREE.Vector3;
}> {
  return new Promise((resolve, reject) => {
    loader.load(
      url,
      (gltf) => {
        const vrm = gltf.userData.vrm as VRM | undefined;
        if (!vrm) {
          reject(new Error("Resolved asset does not contain a VRM payload."));
          return;
        }

        VRMUtils.removeUnnecessaryVertices(vrm.scene);
        VRMUtils.combineSkeletons(vrm.scene);

        vrm.scene.traverse((object: THREE.Object3D) => {
          object.frustumCulled = false;
        });

        const group = new THREE.Group();
        group.add(vrm.scene);
        targetScene.add(group);

        const lookAt = vrm.lookAt;
        if (lookAt) {
          const targetDirection = new THREE.Vector3(0, 0, -1);
          const quaternion = new THREE.Quaternion();
          quaternion.setFromUnitVectors(lookAt.faceFront.clone().normalize(), targetDirection.normalize());
          group.quaternion.premultiply(quaternion);
          group.updateMatrixWorld(true);
        }

        vrm.springBoneManager?.reset();

        const box = computeBoundingBox(vrm.scene);
        const size = new THREE.Vector3();
        const center = new THREE.Vector3();
        box.getSize(size);
        box.getCenter(center);
        center.y += size.y / 5;

        const fov = 40;
        const radians = (fov / 2 * Math.PI) / 180;
        const cameraOffset = new THREE.Vector3(
          size.x / 16,
          size.y / 8,
          -(size.y / 3) / Math.tan(radians),
        );

        resolve({
          vrm,
          group,
          center,
          size,
          cameraOffset,
        });
      },
      undefined,
      reject,
    );
  });
}

/**
 * 计算 VRM 可见网格的包围盒。
 */
function computeBoundingBox(root: THREE.Object3D): THREE.Box3 {
  const box = new THREE.Box3();
  const childBox = new THREE.Box3();

  root.updateMatrixWorld(true);

  root.traverse((object) => {
    if (!object.visible) {
      return;
    }

    const mesh = object as THREE.Mesh;
    if (!mesh.isMesh || !mesh.geometry) {
      return;
    }

    if (mesh.name.startsWith("VRMC_springBone_collider")) {
      return;
    }

    if (!mesh.geometry.boundingBox) {
      mesh.geometry.computeBoundingBox();
    }

    childBox.copy(mesh.geometry.boundingBox!);
    childBox.applyMatrix4(mesh.matrixWorld);
    box.union(childBox);
  });

  return box;
}

defineExpose({
  resetInteraction,
  replayGreeting,
});
</script>

<template>
  <div
    ref="stageSurfaceRef"
    :class="[
      'avatar-stage',
      `avatar-stage--${props.avatar.mode}`,
      `is-${sceneMode}`,
      { 'is-drag-ready': isDragReady, 'is-dragging': isDragging },
    ]"
    @pointerdown="handlePointerDown"
    @pointermove="handlePointerMove"
    @pointerup="handlePointerUp"
    @pointercancel="handlePointerUp"
  >
    <div ref="sceneHostRef" class="avatar-stage-scene" />
    <img
      v-if="sceneMode !== 'vrm' && props.avatar.avatarUri"
      class="avatar-stage-fallback-image"
      :src="props.avatar.avatarUri"
      alt="Code Agent Avatar Background"
    >
    <div v-else-if="sceneMode !== 'vrm'" class="avatar-stage-fallback">
      CA
    </div>
    <div class="avatar-stage-scrim" />
    <div
      ref="runtimeHostRef"
      class="avatar-stage-runtime-host"
      :data-avatar-host-id="props.avatarState.runtimeHostId"
    />
  </div>
</template>
