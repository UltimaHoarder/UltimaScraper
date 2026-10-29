import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

export default function InfrastructureScene({ motion, active }: { motion: boolean; active: boolean }) {
  const container = useRef<HTMLDivElement>(null);
  const options = useRef({ motion, active });
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => { options.current = { motion, active }; }, [motion, active]);

  useEffect(() => {
    const host = container.current;
    if (!host) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
    } catch {
      queueMicrotask(() => setUnavailable(true));
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    renderer.setClearColor(0x1a1f20, 0);
    host.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-9, 9, 4, -4, 0.1, 100);
    camera.position.set(9, 11, 16);
    camera.lookAt(0, 0, 0);
    const infrastructure = new THREE.Group();
    scene.add(infrastructure);
    const geometries: THREE.BufferGeometry[] = [];
    const materials: THREE.Material[] = [];
    const cube = new THREE.BoxGeometry(0.8, 0.7, 0.8);
    const edges = new THREE.EdgesGeometry(cube);
    const base = new THREE.BoxGeometry(3.5, 0.1, 3.6);
    const baseEdges = new THREE.EdgesGeometry(base);
    geometries.push(cube, edges, base, baseEdges);
    const surface = new THREE.MeshBasicMaterial({ color: 0x293234 });
    const cyan = new THREE.LineBasicMaterial({ color: 0x24aac3, transparent: true, opacity: 0.8 });
    const white = new THREE.LineBasicMaterial({ color: 0xb8c7c8, transparent: true, opacity: 0.65 });
    const grey = new THREE.LineBasicMaterial({ color: 0x526264 });
    materials.push(surface, cyan, white, grey);
    [-5, 0, 5].forEach((x, column) => {
      const deck = new THREE.Mesh(base, surface);
      deck.position.set(x, -0.7, 0);
      infrastructure.add(deck);
      const outline = new THREE.LineSegments(baseEdges, grey);
      outline.position.copy(deck.position);
      infrastructure.add(outline);
      for (let row = 0; row < 3; row++) {
        for (let slot = 0; slot < 3; slot++) {
          const unit = new THREE.Mesh(cube, surface);
          unit.position.set(x + (slot - 1) * 1.1, -0.28 + (column === 2 ? 0.22 : 0), (row - 1) * 1.1);
          infrastructure.add(unit);
          const outline = new THREE.LineSegments(edges, column === 1 ? cyan : white);
          outline.position.copy(unit.position);
          infrastructure.add(outline);
        }
      }
    });
    const routes: THREE.Vector3[][] = [-1.1, 0, 1.1].map((z) => [
      new THREE.Vector3(-5, 0.3, z), new THREE.Vector3(-2.5, 0.3, z),
      new THREE.Vector3(0, 0.3, z), new THREE.Vector3(2.5, 0.3, z), new THREE.Vector3(5, 0.3, z),
    ]);
    const packets: THREE.Mesh[] = [];
    const packetGeometry = new THREE.BoxGeometry(0.14, 0.14, 0.14);
    const packetMaterial = new THREE.MeshBasicMaterial({ color: 0x24aac3 });
    geometries.push(packetGeometry);
    materials.push(packetMaterial);
    routes.forEach((route) => {
      const geometry = new THREE.BufferGeometry().setFromPoints(route);
      geometries.push(geometry);
      infrastructure.add(new THREE.Line(geometry, cyan));
      const packet = new THREE.Mesh(packetGeometry, packetMaterial);
      packet.position.copy(route[0]);
      packets.push(packet);
      infrastructure.add(packet);
    });
    const grid = new THREE.GridHelper(24, 24, 0x343a3b, 0x343a3b);
    grid.position.y = -0.85;
    scene.add(grid);
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    let visible = true;
    let lost = false;
    let lastRender = 0;
    let pointerX = 0;
    let dirty = true;
    let previousOptions = '';
    const resize = () => {
      const width = host.clientWidth;
      const height = host.clientHeight;
      if (!width || !height) return;
      renderer.setSize(width, height);
      const aspect = width / height;
      const span = Math.max(5, 17 / aspect);
      camera.left = -span * aspect / 2;
      camera.right = span * aspect / 2;
      camera.top = span / 2;
      camera.bottom = -span / 2;
      camera.updateProjectionMatrix();
      dirty = true;
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    const intersection = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; });
    intersection.observe(host);
    const pointer = (event: PointerEvent) => { pointerX = (event.clientX - host.getBoundingClientRect().left) / host.clientWidth - 0.5; dirty = true; };
    const resetPointer = () => { pointerX = 0; dirty = true; };
    const contextLost = (event: Event) => { event.preventDefault(); lost = true; setUnavailable(true); };
    renderer.domElement.addEventListener('webglcontextlost', contextLost);
    host.addEventListener('pointermove', pointer);
    host.addEventListener('pointerleave', resetPointer);
    const animate = (timestamp: number) => {
      frame = requestAnimationFrame(animate);
      if (!visible || document.hidden || lost || timestamp - lastRender < 50) return;
      const moving = options.current.motion && !reduced.matches;
      const signature = `${moving}:${options.current.active}`;
      if (signature !== previousOptions) dirty = true;
      if (!dirty && !(moving && options.current.active)) return;
      previousOptions = signature;
      dirty = false;
      lastRender = timestamp;
      infrastructure.rotation.y = moving ? pointerX * 0.1 : 0;
      packets.forEach((packet, index) => {
        packet.visible = options.current.active;
        packet.position.x = moving ? -5 + ((timestamp / 2400 + index / 3) % 1) * 10 : index * 2 - 2;
      });
      renderer.render(scene, camera);
    };
    resize();
    frame = requestAnimationFrame(animate);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      intersection.disconnect();
      host.removeEventListener('pointermove', pointer);
      host.removeEventListener('pointerleave', resetPointer);
      renderer.domElement.removeEventListener('webglcontextlost', contextLost);
      geometries.forEach((geometry) => geometry.dispose());
      materials.forEach((material) => material.dispose());
      grid.geometry.dispose();
      (grid.material as THREE.Material).dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div className="atlas-scene" ref={container} aria-hidden="true">
    {unavailable && <div className="atlas-scene-fallback"><span>WORKERS</span><i /><span>ROUTES</span><i /><span>STORAGE</span></div>}
  </div>;
}
