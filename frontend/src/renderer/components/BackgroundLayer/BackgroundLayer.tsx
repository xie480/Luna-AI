import React, { useEffect, useRef } from 'react';
import { useSystemStore } from '../../stores/systemStore';
import './BackgroundLayer.css';

export const BackgroundLayer: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const connectionStatus = useSystemStore((state) => state.connectionStatus);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let particles: { x: number; y: number; speed: number; size: number; opacity: number }[] = [];

    const resizeCanvas = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      initParticles();
    };

    const initParticles = () => {
      particles = [];
      const numParticles = Math.floor((canvas.width * canvas.height) / 15000);
      for (let i = 0; i < numParticles; i++) {
        particles.push({
          x: Math.random() * canvas.width,
          y: Math.random() * canvas.height,
          speed: 0.2 + Math.random() * 0.5,
          size: 1 + Math.random() * 2,
          opacity: 0.1 + Math.random() * 0.3,
        });
      }
    };

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      
      // 根据连接状态调整背景颜色和粒子速度
      const isConnected = connectionStatus === 'connected';
      const baseSpeedMultiplier = isConnected ? 1 : 0.2;

      particles.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(0, 255, 200, ${p.opacity})`;
        ctx.fill();

        p.x += p.speed * baseSpeedMultiplier;

        if (p.x > canvas.width) {
          p.x = 0;
          p.y = Math.random() * canvas.height;
        }
      });

      // 绘制横向流动的微弱线条
      ctx.fillStyle = 'rgba(0, 255, 200, 0.02)';
      for (let i = 0; i < 5; i++) {
        const y = (Date.now() / 50 + i * 200) % canvas.height;
        ctx.fillRect(0, y, canvas.width, 1);
      }

      animationFrameId = requestAnimationFrame(draw);
    };

    window.addEventListener('resize', resizeCanvas);
    resizeCanvas();
    draw();

    return () => {
      window.removeEventListener('resize', resizeCanvas);
      cancelAnimationFrame(animationFrameId);
    };
  }, [connectionStatus]);

  return (
    <div className="background-layer">
      <canvas ref={canvasRef} className="background-canvas" />
      <div className="background-overlay"></div>
    </div>
  );
};
