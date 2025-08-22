import React, { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, Environment, ContactShadows, useGLTF, Sky } from "@react-three/drei";
import * as THREE from "three";
import SunCalc from "suncalc"; // npm i suncalc

// In dev (Vite on 5173) go to Flask at 5000; in prod use same origin.
const LEGACY_URL = (import.meta.env.DEV ? "http://127.0.0.1:5000" : "") + "/legacy";

/* ---------- helpers ---------- */
function centerScaleGround(object, targetSize = 6) {
  const box = new THREE.Box3().setFromObject(object);
  const size = new THREE.Vector3(); box.getSize(size);
  const center = new THREE.Vector3(); box.getCenter(center);
  object.position.sub(center);
  const newBox = new THREE.Box3().setFromObject(object);
  object.position.y -= newBox.min.y;
  const maxDim = Math.max(size.x, size.y, size.z) || 1;
  object.scale.setScalar(targetSize / maxDim);
}

function frameCameraToObject(camera, controls, object, factor = 0.6) {
  const box = new THREE.Box3().setFromObject(object);
  const size = new THREE.Vector3(); box.getSize(size);
  const center = new THREE.Vector3(); box.getCenter(center);
  const maxDim = Math.max(size.x, size.y, size.z) || 1;
  const fov = (camera.fov * Math.PI) / 180;
  const distance = Math.abs(maxDim / (2 * Math.tan(fov / 2))) * factor;

  camera.position.copy(center).add(new THREE.Vector3(distance, 0, 0));
  camera.updateProjectionMatrix();

  if (controls) {
    controls.target.copy(center);
    controls.minDistance = maxDim * 0.6;
    controls.maxDistance = Math.min(maxDim * 6.0, 200);
    controls.update();
  }
}

function FitOnceOnMount({ targetRef }) {
  const didFit = useRef(false);
  const { camera, controls } = useThree();
  useEffect(() => {
    if (!didFit.current && targetRef.current) {
      camera.near = 0.1;
      camera.far = 10000;
      camera.updateProjectionMatrix();
      frameCameraToObject(camera, controls, targetRef.current, 2);
      didFit.current = true;
    }
  }, [camera, controls, targetRef]);
  return null;
}

/* ---------- brushed + horizontal seams bump ---------- */
function makeBrushedWithLinesTexture({
  size = 512, noise = 0.3, streaks = 1.2, repeat = 8, bands = 5, lineStrength = 110, lineWidth = 3
} = {}) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const ctx = c.getContext("2d");

  ctx.fillStyle = "#808080";
  ctx.fillRect(0, 0, size, size);

  ctx.globalAlpha = 0.08;
  ctx.strokeStyle = "#a0a0a0";
  const lines = Math.floor(size * 2.0 * streaks);
  for (let i = 0; i < lines; i++) {
    const jitter = (Math.random() - 0.5) * noise * 6.0;
    const y = Math.floor((i / lines) * size);
    ctx.beginPath();
    ctx.moveTo(0, y + jitter);
    ctx.lineTo(size, y - jitter);
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  ctx.globalAlpha = 1.0;
  const seam = 128 - Math.max(0, Math.min(127, lineStrength));
  ctx.strokeStyle = `rgb(${seam},${seam},${seam})`;
  ctx.lineWidth = lineWidth;
  const spacing = size / bands;
  for (let i = 1; i < bands; i++) {
    const y = Math.floor(i * spacing);
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(size, y);
    ctx.stroke();
  }

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.LinearSRGBColorSpace;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(repeat, repeat);
  return tex;
}

/* ---------- materials ---------- */
function applyRealisticMaterials(root) {
  const brushedWithLines = makeBrushedWithLinesTexture({
    repeat: 8, bands: 5, lineStrength: 110, lineWidth: 3, noise: 0.3, streaks: 1.2
  });

  root.traverse((o) => {
    if (!o.isMesh) return;
    o.castShadow = true;
    o.receiveShadow = true;

    const meshName = (o.name || "").toLowerCase();

    if (meshName.includes("solpanel_steel_0")) {
      o.material = new THREE.MeshPhysicalMaterial({
        color: new THREE.Color("#c9cdd3"),
        metalness: 0.95,
        roughness: 0.35,
        bumpMap: brushedWithLines,
        bumpScale: 1.6,
        envMapIntensity: 1.15,
        clearcoat: 0.8,
        clearcoatRoughness: 0.1
      });
      return;
    }

    if (meshName.includes("cylinder001_steel_0") || meshName.includes("cylinder002_steel_0")) {
      o.material = new THREE.MeshStandardMaterial({
        color: new THREE.Color("#8e949a"),
        metalness: 0.9,
        roughness: 0.55,
        envMapIntensity: 1.0
      });
      return;
    }

    if (meshName.includes("picture")) {
      o.material = new THREE.MeshPhysicalMaterial({
        map: o.material.map ?? null,
        metalness: 0.0,
        roughness: 0.08,
        clearcoat: 1.0,
        clearcoatRoughness: 0.03,
        envMapIntensity: 1.1
      });
      return;
    }
  });
}

/* ---------- geolocation ---------- */
function useBrowserLocation(defaultLat = 19.0760, defaultLon = 72.8777) {
  const [loc, setLoc] = useState({ lat: defaultLat, lon: defaultLon });
  useEffect(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => setLoc({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => {},
      { enableHighAccuracy: true, maximumAge: 600000, timeout: 6000 }
    );
  }, []);
  return loc;
}

/* ---------- panel component (sun / dual-axis tilt) ---------- */
function SolarPanelModel({ mode }) {
  const panelRef  = useRef();
  const baseQuat  = useRef(new THREE.Quaternion());
  const sunDir    = useRef(new THREE.Vector3(0, 1, 0));

  const { scene } = useGLTF("/solarpanel.glb");
  const root = useMemo(() => scene.clone(true), [scene]);

  const { lat, lon } = useBrowserLocation();

  const LIMITS = useMemo(() => ({
    yawMin:   THREE.MathUtils.degToRad(-170),
    yawMax:   THREE.MathUtils.degToRad(170),
    pitchMin: THREE.MathUtils.degToRad(-5),
    pitchMax: THREE.MathUtils.degToRad(65),
  }), []);

  useEffect(() => {
    applyRealisticMaterials(root);
    centerScaleGround(root, 6);
    panelRef.current = root.getObjectByName("solpanel") || root;
    baseQuat.current.copy(panelRef.current.quaternion);
  }, [root]);

  useEffect(() => {
    const update = () => {
      const { azimuth, altitude } = SunCalc.getPosition(new Date(), lat, lon);
      const x =  Math.sin(azimuth) * Math.cos(altitude);
      const y =  Math.sin(altitude);
      const z =  Math.cos(azimuth) * Math.cos(altitude);
      sunDir.current.set(x, y, z).normalize();
    };
    update();
    const id = setInterval(update, 30000);
    return () => clearInterval(id);
  }, [lat, lon]);

  useFrame((state) => {
    if (!panelRef.current) return;

    if (mode === "spin") {
      const T = 8;
      const w = (Math.PI * 2) / T;
      const t = state.clock.getElapsedTime();

      const pitchDegMin = 8, pitchDegMax = 55;
      const s = (Math.sin(t * w) + 1) / 2;
      const pitch = THREE.MathUtils.degToRad(pitchDegMin + (pitchDegMax - pitchDegMin) * s);
      const yaw   = THREE.MathUtils.degToRad(Math.sin(t * w * 0.35) * 30);

      const qTilt = new THREE.Quaternion().setFromEuler(new THREE.Euler(pitch, yaw, 0, "XYZ"));
      const qFinal = new THREE.Quaternion().copy(baseQuat.current).multiply(qTilt);
      panelRef.current.quaternion.copy(qFinal);
      return;
    }

    const dir = sunDir.current;
    const yawTarget   = Math.atan2(dir.x, dir.z);
    const pitchTarget = Math.atan2(dir.y, Math.hypot(dir.x, dir.z));
    const isNight = dir.y < 0;

    const yaw   = THREE.MathUtils.clamp(yawTarget,   LIMITS.yawMin,   LIMITS.yawMax);
    const pitch = isNight
      ? THREE.MathUtils.clamp(THREE.MathUtils.degToRad(5), LIMITS.pitchMin, LIMITS.pitchMax)
      : THREE.MathUtils.clamp(pitchTarget,                  LIMITS.pitchMin, LIMITS.pitchMax);

    const qDelta = new THREE.Quaternion().setFromEuler(new THREE.Euler(pitch, yaw, 0, "XYZ"));
    const qFinal = new THREE.Quaternion().copy(baseQuat.current).multiply(qDelta);
    panelRef.current.quaternion.rotateTowards(qFinal, 0.02);
  });

  return <primitive object={root} />;
}

/* ---------- App ---------- */
export default function App() {
  const sceneRef = useRef();

  const [mode, setMode] = useState("spin");
  const [autoOrbit, setAutoOrbit] = useState(true);

  const { lat, lon } = useBrowserLocation();
  const [skyPos, setSkyPos] = useState([10, 8, -6]);
  const [bgColor, setBgColor] = useState("#0b0f1a");
  const [envPreset, setEnvPreset] = useState("sunset");
  const [sunLightIntensity, setSunLightIntensity] = useState(1.8);
  const [hemiIntensity, setHemiIntensity] = useState(0.35);

  useEffect(() => {
    const update = () => {
      const { azimuth, altitude } = SunCalc.getPosition(new Date(), lat, lon);
      const r = 100;
      const x = Math.sin(azimuth) * Math.cos(altitude) * r;
      const y = Math.sin(altitude) * r;
      const z = Math.cos(azimuth) * Math.cos(altitude) * r;
      setSkyPos([x, y, z]);

      const isDay = altitude > 0.05;
      if (isDay) {
        setBgColor("#b8d0ff");
        setEnvPreset("sunset");
        setSunLightIntensity(1.8);
        setHemiIntensity(0.35);
      } else {
        setBgColor("#05070d");
        setEnvPreset("night");
        setSunLightIntensity(0.5);
        setHemiIntensity(0.15);
      }
    };
    update();
    const id = setInterval(update, 30000);
    return () => clearInterval(id);
  }, [lat, lon]);

  const initialCamera = useMemo(
    () => ({ position: [0, 1.5, 8], fov: 50, near: 0.1, far: 10000 }),
    []
  );

  return (
    <div style={{ width: "100vw", height: "100vh", position: "relative" }}>
      {/* GET STARTED (→ Flask /legacy) */}
      <button
        onClick={() => window.location.assign(LEGACY_URL)}
        style={{
          position: "absolute", top: 20, right: 20, zIndex: 10,
          padding: "10px 14px", borderRadius: 12,
          background: "#F6AD55", color: "#1a1a1a",
          fontWeight: 700, border: "1px solid #e69b3f",
          boxShadow: "0 6px 16px rgba(0,0,0,0.25)", cursor: "pointer"
        }}
      >
        Get Started
      </button>

      {/* Panel mode toggle */}
      <button
        onClick={() => setMode(mode === "sun" ? "spin" : "sun")}
        style={{
          position: "absolute", top: 20, left: 20, zIndex: 10,
          background: "#2B6CB0", color: "#fff", border: "none",
          padding: "10px 14px", borderRadius: "8px", cursor: "pointer",
          boxShadow: "0 6px 16px rgba(0,0,0,0.25)"
        }}
        title="Toggle Sun Tracking / Dual-Axis Tilt"
      >
        {mode === "sun" ? "Switch to Dual-Axis Tilt" : "Switch to Sun Tracking"}
      </button>

      {/* POV rotate toggle */}
      <button
        onClick={() => setAutoOrbit(v => !v)}
        style={{
          position: "absolute", top: 20, left: 260, zIndex: 10,
          background: autoOrbit ? "#B83280" : "#2B6CB0",
          color: "#fff", border: "none",
          padding: "10px 14px", borderRadius: "8px", cursor: "pointer",
          boxShadow: "0 6px 16px rgba(0,0,0,0.25)"
        }}
        title="Rotate the camera around the panel"
      >
        {autoOrbit ? "Stop POV Rotate" : "Start POV Rotate"}
      </button>

      <Canvas
        camera={initialCamera}
        shadows
        onCreated={({ gl, scene, camera }) => {
          gl.physicallyCorrectLights = true;
          gl.outputColorSpace = THREE.SRGBColorSpace;
          gl.toneMapping = THREE.ACESFilmicToneMapping;
          gl.toneMappingExposure = 1.0;
          gl.shadowMap.enabled = true;
          gl.shadowMap.type = THREE.PCFSoftShadowMap;

          camera.near = 0.1;
          camera.far = 10000;
          camera.updateProjectionMatrix();

          scene.background = new THREE.Color(bgColor);
        }}
      >
        <Sky distance={450000} sunPosition={skyPos} />
        <Environment preset={envPreset} background={false} intensity={1.0} />

        <directionalLight
          position={[8, 14, 6]}
          intensity={sunLightIntensity}
          castShadow
          shadow-mapSize-width={2048}
          shadow-mapSize-height={2048}
          shadow-radius={2}
          shadow-bias={-0.00012}
        />
        <hemisphereLight args={[0xffffff, 0x223344, hemiIntensity]} />
        <directionalLight position={[-10, 8, -6]} intensity={0.28} color={0xa0b7ff} />

        <Suspense fallback={null}>
          <group ref={sceneRef}>
            <SolarPanelModel mode={mode} />
          </group>

          <ContactShadows
            position={[0, 0, 0]}
            scale={22}
            opacity={0.5}
            blur={2.5}
            far={20}
            resolution={1024}
            frames={1}
          />
        </Suspense>

        <OrbitControls
          enableDamping
          dampingFactor={0.08}
          target={[0, 1.5, 0]}
          autoRotate={autoOrbit}
          autoRotateSpeed={2}
          maxDistance={700}
          minDistance={1.5}
        />

        <FitOnceOnMount targetRef={sceneRef} />
      </Canvas>
    </div>
  );
}

useGLTF.preload("/solarpanel.glb");
