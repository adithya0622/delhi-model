/* eslint-disable react/no-unknown-property */
import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import './Lanyard.css';

export interface LanyardCardData {
  title: string;
  subtitle: string;
  aqi: number;
  category: string;
  color: string;
  meta: Array<{ label: string; value: string }>;
  pollutants?: Array<{ name: string; value: string }>;
  note?: string;
  isStation?: boolean;
}

interface LanyardProps {
  data: LanyardCardData;
  onClear?: () => void;
}

// Generate Ultra-HD front and back card textures (2048 x 2900 for razor-sharp clarity)
function generateCardCanvas(data: LanyardCardData, isBack = false): HTMLCanvasElement {
  const W = 2048;
  const H = 2900;
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d');
  if (!ctx) return canvas;

  // Background gradient (Deep Obsidian Glass)
  const bgGrad = ctx.createRadialGradient(W * 0.8, H * 0.2, 80, W * 0.5, H * 0.5, W * 0.9);
  bgGrad.addColorStop(0, '#1c2738');
  bgGrad.addColorStop(0.5, '#0e1520');
  bgGrad.addColorStop(1, '#05090e');
  ctx.fillStyle = bgGrad;
  ctx.fillRect(0, 0, W, H);

  // Carbon grid texture
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
  ctx.lineWidth = 2;
  const gridStep = 64;
  for (let x = 0; x < W; x += gridStep) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, H);
    ctx.stroke();
  }
  for (let y = 0; y < H; y += gridStep) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();
  }

  // Outer Metallic Bevel Border
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.25)';
  ctx.lineWidth = 8;
  ctx.strokeRect(36, 36, W - 72, H - 72);

  // Colored Corner Accent Brackets
  ctx.strokeStyle = data.color || '#3fff75';
  ctx.lineWidth = 12;
  ctx.beginPath();
  ctx.moveTo(36, 200);
  ctx.lineTo(36, 36);
  ctx.lineTo(200, 36);
  ctx.moveTo(W - 200, H - 36);
  ctx.lineTo(W - 36, H - 36);
  ctx.lineTo(W - 36, H - 200);
  ctx.stroke();

  if (!isBack) {
    // ── FRONT FACE ───────────────────────────────────────────────────────────
    // Top Slot
    ctx.fillStyle = '#030508';
    ctx.beginPath();
    ctx.roundRect(W / 2 - 180, 80, 360, 48, 24);
    ctx.fill();
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.35)';
    ctx.lineWidth = 3.5;
    ctx.stroke();

    // Top Header
    ctx.fillStyle = 'rgba(255, 255, 255, 0.75)';
    ctx.font = '600 42px "IBM Plex Mono", monospace';
    ctx.fillText('NCR·72 AMBIENT PASS', 100, 240);

    ctx.fillStyle = data.color;
    ctx.beginPath();
    ctx.arc(W - 130, 226, 18, 0, Math.PI * 2);
    ctx.fill();

    // Title / Station Name (Large & Bold)
    ctx.fillStyle = '#FFFFFF';
    ctx.font = '700 84px "IBM Plex Sans", sans-serif';
    const titleText = data.title.length > 22 ? data.title.substring(0, 20) + '…' : data.title;
    ctx.fillText(titleText, 100, 370);

    // Subtitle
    ctx.fillStyle = '#94a3b8';
    ctx.font = '600 44px "IBM Plex Mono", monospace';
    ctx.fillText(data.subtitle.toUpperCase(), 100, 440);

    // Main Glowing AQI Box
    const aqiBoxY = 520;
    const aqiBoxH = 620;
    const boxGrad = ctx.createLinearGradient(100, aqiBoxY, W - 100, aqiBoxY + aqiBoxH);
    boxGrad.addColorStop(0, 'rgba(255, 255, 255, 0.12)');
    boxGrad.addColorStop(1, 'rgba(255, 255, 255, 0.03)');
    ctx.fillStyle = boxGrad;
    ctx.beginPath();
    ctx.roundRect(100, aqiBoxY, W - 200, aqiBoxH, 36);
    ctx.fill();
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
    ctx.lineWidth = 4;
    ctx.stroke();

    // Glow aura behind AQI
    const glowGrad = ctx.createRadialGradient(W / 2, aqiBoxY + 250, 40, W / 2, aqiBoxY + 250, 360);
    glowGrad.addColorStop(0, data.color + '55');
    glowGrad.addColorStop(1, 'transparent');
    ctx.fillStyle = glowGrad;
    ctx.fillRect(100, aqiBoxY, W - 200, aqiBoxH);

    // AQI Number (Giant & Crystal Clear)
    ctx.fillStyle = data.color;
    ctx.font = '800 320px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText(String(data.aqi), W / 2, aqiBoxY + 340);

    // Category (Large & High Contrast)
    ctx.fillStyle = '#FFFFFF';
    ctx.font = '800 68px "IBM Plex Mono", monospace';
    ctx.letterSpacing = '6px';
    ctx.fillText(data.category.toUpperCase(), W / 2, aqiBoxY + 490);
    ctx.textAlign = 'left';

    // ── Telemetry Key-Value Grid (The 4 Prominent Rounded Items) ───────────────
    const gridY = 1240;
    data.meta.slice(0, 4).forEach((item, idx) => {
      const col = idx % 2;
      const row = Math.floor(idx / 2);
      const cardW = 880;
      const cardH = 220;
      const posX = 100 + col * 968;
      const posY = gridY + row * 260;

      // Capsule Background for each telemetry item
      ctx.fillStyle = 'rgba(255, 255, 255, 0.05)';
      ctx.beginPath();
      ctx.roundRect(posX, posY, cardW, cardH, 24);
      ctx.fill();
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';
      ctx.lineWidth = 2.5;
      ctx.stroke();

      // Label (High Contrast Cyan-Blue, Large & Crisp)
      ctx.fillStyle = '#93c5fd';
      ctx.font = '700 44px "IBM Plex Mono", monospace';
      ctx.fillText(item.label.toUpperCase(), posX + 40, posY + 75);

      // Value (Ultra-Bold White, Highly Legible)
      ctx.fillStyle = '#FFFFFF';
      ctx.font = '800 68px "IBM Plex Mono", monospace';
      ctx.fillText(item.value, posX + 40, posY + 160);
    });

    // ── Criteria Pollutants Section (Bottom Rounded Items) ────────────────────
    const polY = 1820;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.18)';
    ctx.lineWidth = 3.5;
    ctx.beginPath();
    ctx.moveTo(100, polY);
    ctx.lineTo(W - 100, polY);
    ctx.stroke();

    ctx.fillStyle = '#e2e8f0';
    ctx.font = '700 48px "IBM Plex Mono", monospace';
    ctx.fillText('CRITERIA POLLUTANTS (CONC / ROLE)', 100, polY + 70);

    const polItems = data.pollutants && data.pollutants.length > 0
      ? data.pollutants.slice(0, 4)
      : [
          { name: 'PM2.5', value: 'Primary' },
          { name: 'PM10', value: 'Coarse' },
          { name: 'NO2', value: 'Vehicular' },
          { name: 'O3', value: 'Photochem' },
        ];

    polItems.forEach((p, idx) => {
      const col = idx % 2;
      const row = Math.floor(idx / 2);
      const px = 100 + col * 968;
      const py = polY + 160 + row * 170;

      // Pollutant Capsule Pill
      ctx.fillStyle = 'rgba(15, 23, 42, 0.7)';
      ctx.beginPath();
      ctx.roundRect(px, py, 880, 130, 20);
      ctx.fill();
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
      ctx.lineWidth = 2.5;
      ctx.stroke();

      // Pollutant Name Tag
      ctx.fillStyle = data.color;
      ctx.font = '800 54px "IBM Plex Mono", monospace';
      ctx.fillText(p.name, px + 40, py + 85);

      // Value
      ctx.fillStyle = '#FFFFFF';
      ctx.font = '700 54px "IBM Plex Mono", monospace';
      ctx.fillText(p.value, px + 280, py + 85);
    });

    // Hologram Security Strip at bottom
    const holoY = H - 260;
    const holoGrad = ctx.createLinearGradient(100, holoY, W - 100, holoY);
    holoGrad.addColorStop(0, '#ff007f66');
    holoGrad.addColorStop(0.25, '#00f0ff66');
    holoGrad.addColorStop(0.5, '#3fff7566');
    holoGrad.addColorStop(0.75, '#ffb80066');
    holoGrad.addColorStop(1, '#ff007f66');
    ctx.fillStyle = holoGrad;
    ctx.beginPath();
    ctx.roundRect(100, holoY, W - 200, 100, 20);
    ctx.fill();

    ctx.fillStyle = '#FFFFFF';
    ctx.font = '700 32px "IBM Plex Mono", monospace';
    ctx.fillText('SECURE REAL-TIME ATMOSPHERIC SENSING TELEMETRY', 140, holoY + 60);

  } else {
    // ── BACK FACE (Ultra-HD) ──────────────────────────────────────────────────
    ctx.fillStyle = '#030508';
    ctx.beginPath();
    ctx.roundRect(W / 2 - 180, 80, 360, 48, 24);
    ctx.fill();

    ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
    ctx.font = '700 46px "IBM Plex Mono", monospace';
    ctx.fillText('CPCB NATIONAL AIR QUALITY INDEX', 100, 260);

    const scaleData = [
      { name: 'GOOD', range: '0-50', color: '#4FB477' },
      { name: 'SATISFACTORY', range: '51-100', color: '#9FC93C' },
      { name: 'MODERATE', range: '101-200', color: '#EFC02D' },
      { name: 'POOR', range: '201-300', color: '#F2892F' },
      { name: 'VERY POOR', range: '301-400', color: '#E8503C' },
      { name: 'SEVERE', range: '401-500+', color: '#C0356A' },
    ];

    scaleData.forEach((item, i) => {
      const sy = 380 + i * 210;
      ctx.fillStyle = 'rgba(255, 255, 255, 0.06)';
      ctx.beginPath();
      ctx.roundRect(100, sy, W - 200, 160, 26);
      ctx.fill();

      ctx.fillStyle = item.color;
      ctx.beginPath();
      ctx.roundRect(140, sy + 30, 32, 100, 10);
      ctx.fill();

      ctx.fillStyle = '#FFFFFF';
      ctx.font = '800 52px "IBM Plex Mono", monospace';
      ctx.fillText(item.name, 210, sy + 100);

      ctx.fillStyle = 'rgba(255, 255, 255, 0.75)';
      ctx.font = '700 44px "IBM Plex Mono", monospace';
      ctx.fillText(item.range, W - 420, sy + 100);
    });

    const instY = 1780;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.55)';
    ctx.font = '500 40px sans-serif';
    ctx.fillText('• Physics-informed deterministic coupling with 43 CAAQMS nodes.', 100, instY);
    ctx.fillText('• Grab, rotate or release the 3D lanyard pass to inspect details.', 100, instY + 80);

    ctx.fillStyle = 'rgba(255, 255, 255, 0.18)';
    ctx.fillRect(100, H - 420, 220, 220);
    ctx.fillStyle = data.color;
    ctx.fillRect(135, H - 385, 150, 150);

    ctx.fillStyle = '#FFFFFF';
    ctx.font = '700 38px "IBM Plex Mono", monospace';
    ctx.fillText('DIGITAL SENSOR CERTIFICATE', 370, H - 310);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.65)';
    ctx.fillText('ID: CPCB-NCR-72-GEO-LOCK', 370, H - 240);
  }

  return canvas;
}

export function Lanyard({ data, onClear }: LanyardProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Physics points for tall hanging strap holding elevated enlarged card
  const physicsRef = useRef({
    points: [
      { x: 0, y: 7.2, z: 0, oldX: 0, oldY: 7.2, oldZ: 0, pinned: true },
      { x: 0.03, y: 6.0, z: 0, oldX: 0.03, oldY: 6.0, oldZ: 0, pinned: false },
      { x: 0.05, y: 4.8, z: 0, oldX: 0.05, oldY: 4.8, oldZ: 0, pinned: false },
      { x: 0.03, y: 3.6, z: 0, oldX: 0.03, oldY: 3.6, oldZ: 0, pinned: false },
      { x: 0, y: 2.4, z: 0, oldX: 0, oldY: 2.4, oldZ: 0, pinned: false },
    ],
    cardRot: { x: 0, y: 0, z: 0, vx: 0, vy: 0, vz: 0 },
    isDragging: false,
    dragPlaneZ: 0,
  });

  const mouseRef = useRef({ x: 0, y: 0, prevX: 0, prevY: 0, down: false });

  // Textures
  const frontTexRef = useRef<THREE.CanvasTexture | null>(null);
  const backTexRef = useRef<THREE.CanvasTexture | null>(null);

  useEffect(() => {
    const frontC = generateCardCanvas(data, false);
    const backC = generateCardCanvas(data, true);

    const fTex = new THREE.CanvasTexture(frontC);
    fTex.colorSpace = THREE.SRGBColorSpace;
    fTex.minFilter = THREE.LinearFilter;
    fTex.magFilter = THREE.LinearFilter;
    fTex.generateMipmaps = false;
    fTex.anisotropy = 16;
    fTex.needsUpdate = true;
    frontTexRef.current = fTex;

    const bTex = new THREE.CanvasTexture(backC);
    bTex.colorSpace = THREE.SRGBColorSpace;
    bTex.minFilter = THREE.LinearFilter;
    bTex.magFilter = THREE.LinearFilter;
    bTex.generateMipmaps = false;
    bTex.anisotropy = 16;
    bTex.needsUpdate = true;
    backTexRef.current = bTex;
  }, [data]);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const width = container.clientWidth || 460;
    const height = container.clientHeight || 800;

    // Three.js Scene Setup
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, width / height, 0.1, 100);
    camera.position.set(0, 0.35, 21.0);

    const renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: true,
      powerPreference: 'high-performance',
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2.5));
    renderer.setClearColor(0x000000, 0);

    // Lights
    const ambient = new THREE.AmbientLight(0xffffff, 2.4);
    scene.add(ambient);

    const dirLight = new THREE.DirectionalLight(0xffffff, 2.9);
    dirLight.position.set(6, 14, 10);
    scene.add(dirLight);

    const neonLight = new THREE.DirectionalLight(data.color || 0x3fff75, 2.2);
    neonLight.position.set(-7, -4, 5);
    scene.add(neonLight);

    const backLight = new THREE.PointLight(0xffffff, 1.5);
    backLight.position.set(0, 1, -6);
    scene.add(backLight);

    // Ceiling Anchor Bracket at top
    const bracketMesh = new THREE.Mesh(
      new THREE.BoxGeometry(1.3, 0.32, 0.35),
      new THREE.MeshStandardMaterial({ metalness: 0.9, roughness: 0.2, color: 0x334155 })
    );
    bracketMesh.position.set(0, 7.18, 0);
    scene.add(bracketMesh);

    // ── 3D Card Group (Slightly enlarged for perfect prominence) ──
    const cardGroup = new THREE.Group();
    scene.add(cardGroup);

    const cardW = 5.2;
    const cardH = 7.4;
    const cardDepth = 0.045;

    const frontMat = new THREE.MeshPhysicalMaterial({
      map: frontTexRef.current,
      roughness: 0.2,
      metalness: 0.12,
      clearcoat: 1.0,
      clearcoatRoughness: 0.08,
    });

    const backMat = new THREE.MeshPhysicalMaterial({
      map: backTexRef.current,
      roughness: 0.2,
      metalness: 0.12,
      clearcoat: 1.0,
      clearcoatRoughness: 0.08,
    });

    const frontMesh = new THREE.Mesh(new THREE.BoxGeometry(cardW, cardH, cardDepth), frontMat);
    frontMesh.position.set(0, -cardH / 2, cardDepth / 2);
    cardGroup.add(frontMesh);

    const backMesh = new THREE.Mesh(new THREE.BoxGeometry(cardW, cardH, cardDepth), backMat);
    backMesh.position.set(0, -cardH / 2, -cardDepth / 2);
    backMesh.rotation.y = Math.PI;
    cardGroup.add(backMesh);

    // Metal Clip & Clamp
    const clampMesh = new THREE.Mesh(
      new THREE.BoxGeometry(1.25, 0.42, 0.14),
      new THREE.MeshStandardMaterial({ metalness: 0.95, roughness: 0.15, color: 0xd4d4d8 })
    );
    clampMesh.position.set(0, 0.18, 0);
    cardGroup.add(clampMesh);

    const ringMesh = new THREE.Mesh(
      new THREE.TorusGeometry(0.32, 0.055, 16, 32),
      new THREE.MeshStandardMaterial({ metalness: 0.95, roughness: 0.15, color: 0xe4e4e7 })
    );
    ringMesh.position.set(0, 0.48, 0);
    ringMesh.rotation.x = Math.PI / 2;
    cardGroup.add(ringMesh);

    // ── Rope Tube Mesh ──
    const ropeCurve = new THREE.CatmullRomCurve3(
      physicsRef.current.points.map((p) => new THREE.Vector3(p.x, p.y, p.z))
    );

    const ropeGeo = new THREE.TubeGeometry(ropeCurve, 40, 0.065, 8, false);
    const ropeMat = new THREE.MeshStandardMaterial({
      color: 0x182433,
      roughness: 0.5,
      metalness: 0.35,
    });
    const ropeMesh = new THREE.Mesh(ropeGeo, ropeMat);
    scene.add(ropeMesh);

    // Raycaster for drag interaction
    const raycaster = new THREE.Raycaster();
    const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
    const planeIntersect = new THREE.Vector3();

    const handlePointerDown = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      mouseRef.current = { x, y, prevX: x, prevY: y, down: true };

      raycaster.setFromCamera(new THREE.Vector2(x, y), camera);
      const intersects = raycaster.intersectObjects([frontMesh, backMesh, clampMesh]);
      if (intersects.length > 0) {
        physicsRef.current.isDragging = true;
        canvas.setPointerCapture(e.pointerId);
      }
    };

    const handlePointerMove = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      mouseRef.current.prevX = mouseRef.current.x;
      mouseRef.current.prevY = mouseRef.current.y;
      mouseRef.current.x = x;
      mouseRef.current.y = y;

      if (physicsRef.current.isDragging) {
        raycaster.setFromCamera(new THREE.Vector2(x, y), camera);
        raycaster.ray.intersectPlane(plane, planeIntersect);
        const lastPoint = physicsRef.current.points[physicsRef.current.points.length - 1];
        lastPoint.x = planeIntersect.x;
        lastPoint.y = Math.min(4.5, planeIntersect.y + 3.0);
        lastPoint.z = planeIntersect.z;
      }
    };

    const handlePointerUp = (e: PointerEvent) => {
      physicsRef.current.isDragging = false;
      mouseRef.current.down = false;
      try {
        canvas.releasePointerCapture(e.pointerId);
      } catch (_) {}
    };

    canvas.addEventListener('pointerdown', handlePointerDown);
    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);

    // ── Verlet Physics Animation Loop ──
    let animId: number;
    const gravity = -0.016;
    const segmentLength = 1.22;
    const iterations = 12;

    const animate = () => {
      animId = requestAnimationFrame(animate);

      if (frontMat.map !== frontTexRef.current && frontTexRef.current) {
        frontMat.map = frontTexRef.current;
        frontMat.needsUpdate = true;
      }
      if (backMat.map !== backTexRef.current && backTexRef.current) {
        backMat.map = backTexRef.current;
        backMat.needsUpdate = true;
      }

      const pts = physicsRef.current.points;

      // 1. Verlet integration for rope points
      pts.forEach((p) => {
        if (p.pinned) return;
        const vx = (p.x - p.oldX) * 0.985;
        const vy = (p.y - p.oldY) * 0.985;
        const vz = (p.z - p.oldZ) * 0.985;

        p.oldX = p.x;
        p.oldY = p.y;
        p.oldZ = p.z;

        p.x += vx;
        p.y += vy + gravity;
        p.z += vz;
      });

      // 2. Distance Constraints
      for (let it = 0; it < iterations; it++) {
        for (let i = 0; i < pts.length - 1; i++) {
          const p1 = pts[i];
          const p2 = pts[i + 1];
          const dx = p2.x - p1.x;
          const dy = p2.y - p1.y;
          const dz = p2.z - p1.z;
          const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 0.001;
          const diff = (segmentLength - dist) / dist;
          const factor = 0.5;

          if (!p1.pinned) {
            p1.x -= dx * factor * diff;
            p1.y -= dy * factor * diff;
            p1.z -= dz * factor * diff;
          }
          if (!p2.pinned && !physicsRef.current.isDragging) {
            p2.x += dx * factor * diff;
            p2.y += dy * factor * diff;
            p2.z += dz * factor * diff;
          }
        }
      }

      // 3. Update Rope Mesh Tube
      const curvePts = pts.map((p) => new THREE.Vector3(p.x, p.y, p.z));
      ropeCurve.points = curvePts;
      ropeMesh.geometry.dispose();
      ropeMesh.geometry = new THREE.TubeGeometry(ropeCurve, 40, 0.06, 8, false);

      // 4. Update Card Position & Orientation
      const bottomPt = pts[pts.length - 1];
      const prevPt = pts[pts.length - 2];
      cardGroup.position.set(bottomPt.x, bottomPt.y, bottomPt.z);

      const ropeDir = new THREE.Vector3(bottomPt.x - prevPt.x, bottomPt.y - prevPt.y, bottomPt.z - prevPt.z).normalize();
      const targetRotZ = Math.atan2(ropeDir.x, -ropeDir.y) * 0.8;
      const targetRotX = Math.atan2(ropeDir.z, -ropeDir.y) * 0.8;

      cardGroup.rotation.z += (targetRotZ - cardGroup.rotation.z) * 0.15;
      cardGroup.rotation.x += (targetRotX - cardGroup.rotation.x) * 0.15;

      // Gentle ambient floating sway
      if (!physicsRef.current.isDragging) {
        cardGroup.rotation.y += Math.sin(Date.now() * 0.0015) * 0.002;
      }

      renderer.render(scene, camera);
    };

    animate();

    const handleResize = () => {
      if (!containerRef.current) return;
      const w = containerRef.current.clientWidth;
      const h = containerRef.current.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener('resize', handleResize);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', handleResize);
      canvas.removeEventListener('pointerdown', handlePointerDown);
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
      renderer.dispose();
    };
  }, [data.color]);

  return (
    <div ref={containerRef} className="lanyard-wrapper">
      <canvas ref={canvasRef} />

      {data.isStation && onClear && (
        <button
          type="button"
          onClick={onClear}
          style={{
            position: 'absolute',
            top: '0.85rem',
            right: '0.85rem',
            zIndex: 10,
            background: 'rgba(15, 23, 33, 0.85)',
            border: '1px solid var(--hairline-2)',
            borderRadius: '4px',
            color: 'var(--mist)',
            padding: '0.35rem 0.65rem',
            fontSize: '11px',
            fontFamily: 'var(--mono)',
            cursor: 'pointer',
            backdropFilter: 'blur(8px)',
            transition: 'all 0.2s ease',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = '#FFFFFF';
            e.currentTarget.style.borderColor = 'var(--live)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = 'var(--mist)';
            e.currentTarget.style.borderColor = 'var(--hairline-2)';
          }}
        >
          ← Network View
        </button>
      )}
    </div>
  );
}
export default Lanyard;
