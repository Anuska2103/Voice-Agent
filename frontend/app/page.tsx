"use client";

import { useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { Canvas, useFrame } from "@react-three/fiber";
import { AnimatePresence, motion } from "framer-motion";

import { VoiceAgentPanel } from "@/components/VoiceAgentPanel";

const VERTEX_SHADER = `
varying vec2 vUv;

void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const FRAGMENT_SHADER = `
uniform float uTime;
uniform vec2 uMouse;
varying vec2 vUv;

float rand(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);

  float a = rand(i + vec2(0.0, 0.0));
  float b = rand(i + vec2(1.0, 0.0));
  float c = rand(i + vec2(0.0, 1.0));
  float d = rand(i + vec2(1.0, 1.0));

  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

void main() {
  vec2 uv = vUv;
  vec2 m = uMouse;

  float t = uTime * 0.45;
  uv.x += sin((uv.y * 8.0) + t) * 0.05;
  uv.y += cos((uv.x * 10.0) + t * 1.2) * 0.03;

  float d = distance(uv, m);
  float ripple = sin(d * 26.0 - uTime * 2.6) * 0.018;
  uv += vec2(ripple);

  float flowA = 0.5 + 0.5 * sin((uv.x * 6.5) + t);
  float flowB = 0.5 + 0.5 * cos((uv.y * 7.0) - (t * 0.9));
  float grain = noise((uv * 3.2) + (uTime * 0.15));

  vec3 sapGreen = vec3(0.37, 0.55, 0.27);
  vec3 oliveGreen = vec3(0.50, 0.56, 0.23);
  vec3 seaBlue = vec3(0.17, 0.52, 0.70);
  vec3 warmYellow = vec3(0.92, 0.82, 0.33);

  vec3 color = mix(sapGreen, oliveGreen, flowA);
  color = mix(color, seaBlue, flowB * 0.55);
  color = mix(color, warmYellow, smoothstep(0.1, 0.95, flowA * flowB));

  float mouseGlow = smoothstep(0.5, 0.0, d);
  color += vec3(0.09, 0.1, 0.06) * mouseGlow;
  color += (grain - 0.5) * 0.025;

  gl_FragColor = vec4(color, 1.0);
}
`;

function GradientPlane({ mouse }: { mouse: React.MutableRefObject<THREE.Vector2> }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uMouse: { value: new THREE.Vector2(0.5, 0.5) },
    }),
    [],
  );

  useFrame((state) => {
    uniforms.uTime.value = state.clock.elapsedTime;
    uniforms.uMouse.value.lerp(mouse.current, 0.08);

    if (meshRef.current) {
      meshRef.current.rotation.z = Math.sin(state.clock.elapsedTime * 0.08) * 0.04;
    }
  });

  return (
    <mesh ref={meshRef} scale={[9, 9, 1]}>
      <planeGeometry args={[1, 1, 64, 64]} />
      <shaderMaterial
        uniforms={uniforms}
        vertexShader={VERTEX_SHADER}
        fragmentShader={FRAGMENT_SHADER}
      />
    </mesh>
  );
}

function LineAgentDiagram() {
  return (
    <motion.svg
      className="agentLineArt"
      viewBox="0 0 360 360"
      role="img"
      aria-label="Line drawing of a computer monitor with sound waves"
      initial={{ opacity: 0.7 }}
      animate={{ opacity: [0.65, 1, 0.7] }}
      transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
    >
      <motion.path
        d="M68 86 H268 C280 86 290 96 290 108 V208 C290 220 280 230 268 230 H68 C56 230 46 220 46 208 V108 C46 96 56 86 68 86 Z"
        className="lineStroke"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: [0, 1, 1, 0], opacity: [0, 1, 1, 0] }}
        transition={{ duration: 4.8, times: [0, 0.45, 0.75, 1], repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.path
        d="M70 112 H266 V204 H70 Z"
        className="lineStroke"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: [0, 1, 1, 0], opacity: [0, 1, 1, 0] }}
        transition={{ duration: 4.8, delay: 0.14, times: [0, 0.45, 0.75, 1], repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.path
        d="M148 230 L136 274 H200 L188 230"
        className="lineStroke"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: [0, 1, 1, 0], opacity: [0, 1, 1, 0] }}
        transition={{ duration: 4.8, delay: 0.23, times: [0, 0.45, 0.75, 1], repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.path
        d="M112 274 H224"
        className="lineStroke"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: [0, 1, 1, 0], opacity: [0, 1, 1, 0] }}
        transition={{ duration: 4.8, delay: 0.33, times: [0, 0.45, 0.75, 1], repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.path
        d="M106 148 C122 130 144 124 170 128 C198 132 214 148 226 168"
        className="lineStroke"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: [0, 1, 1, 0], opacity: [0, 1, 1, 0] }}
        transition={{ duration: 4.8, delay: 0.4, times: [0, 0.45, 0.75, 1], repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.path
        d="M302 136 C316 142 324 152 328 166 C324 180 316 190 302 196"
        className="lineStroke"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: [0, 1, 1, 0], opacity: [0, 1, 1, 0] }}
        transition={{ duration: 4.8, delay: 0.48, times: [0, 0.45, 0.75, 1], repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.path
        d="M318 120 C338 130 350 146 354 166 C350 186 338 202 318 212"
        className="lineStroke"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: [0, 1, 1, 0], opacity: [0, 1, 1, 0] }}
        transition={{ duration: 4.8, delay: 0.58, times: [0, 0.45, 0.75, 1], repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.path
        d="M293 162 L293 170"
        className="lineStroke"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: [0, 1, 1, 0], opacity: [0, 1, 1, 0] }}
        transition={{ duration: 4.8, delay: 0.68, times: [0, 0.45, 0.75, 1], repeat: Infinity, ease: "easeInOut" }}
      />
    </motion.svg>
  );
}

export default function Home() {
  const [isArmed, setIsArmed] = useState(false);
  const [isMainOpen, setIsMainOpen] = useState(false);
  const mouseRef = useRef(new THREE.Vector2(0.5, 0.5));

  function handlePointerMove(event: React.PointerEvent<HTMLElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = 1 - (event.clientY - rect.top) / rect.height;
    mouseRef.current.set(THREE.MathUtils.clamp(x, 0, 1), THREE.MathUtils.clamp(y, 0, 1));
  }

  function handleExploreClick() {
    if (!isArmed) {
      setIsArmed(true);
      return;
    }
    setIsMainOpen(true);
  }

  return (
    <main className="landingRoot" onPointerMove={handlePointerMove}>
      <div className="gradientLayer" aria-hidden="true">
        <Canvas camera={{ position: [0, 0, 1.8], fov: 52 }}>
          <GradientPlane mouse={mouseRef} />
        </Canvas>
      </div>

      <AnimatePresence mode="wait">
        {!isMainOpen ? (
          <motion.section
            key="landing"
            className="landingStage"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, filter: "blur(8px)", scale: 0.98 }}
            transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="diagramWrap">
              <LineAgentDiagram />
            </div>

            <section className="introCard">
              <p className="kicker">REAL-TIME VOICE AGENT</p>
              <h1>EstateMind</h1>
              <p className="subtitle">A real-time voice agent for the people of Kolkata.</p>

              <motion.button
                type="button"
                className="exploreButton"
                onClick={handleExploreClick}
                initial={{ y: 0 }}
                animate={{ y: isArmed ? 130 : 0 }}
                transition={{ type: "spring", stiffness: 95, damping: 14 }}
              >
                {isArmed ? "Open Main Page" : "Let's Explore"}
              </motion.button>

              <motion.p
                className="exploreHint"
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: isArmed ? 1 : 0, y: isArmed ? 8 : -8 }}
                transition={{ duration: 0.35 }}
              >
                Click once more to enter.
              </motion.p>
            </section>
          </motion.section>
        ) : (
          <motion.section
            key="main"
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
            className="shell"
          >
            <section className="hero">
              <p className="kicker">REAL-TIME VOICE AGENT</p>
              <h1>EstateMind</h1>
              <p className="subtitle">A real-time voice agent for the people of Kolkata.</p>
            </section>
            <VoiceAgentPanel />
          </motion.section>
        )}
      </AnimatePresence>
    </main>
  );
}
