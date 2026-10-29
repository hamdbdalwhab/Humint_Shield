/**
 * Decorative Matrix rain for the SOC simulation.
 *
 * It is intentionally lightweight and purely visual: no data is read, no
 * endpoint is contacted, and it disables itself for users who prefer reduced
 * motion.
 */
import { useEffect, useRef } from 'react';

export function MatrixRain({ opacity = 0.16 }: { opacity?: number }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) return undefined;

    const ctx = canvas.getContext('2d');
    if (!ctx) return undefined;

    const fontSize = 15;
    const glyphs = '01ABCDEF<>/{}[]$#*+=?01';
    let width = 0;
    let height = 0;
    let columns: number[] = [];
    let raf = 0;

    const resize = () => {
      const parent = canvas.parentElement;
      const rect = parent?.getBoundingClientRect();
      width = Math.max(1, Math.floor(rect?.width ?? window.innerWidth));
      height = Math.max(1, Math.floor(rect?.height ?? window.innerHeight));
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      columns = Array.from(
        { length: Math.ceil(width / fontSize) },
        () => Math.random() * -height,
      );
    };

    resize();
    window.addEventListener('resize', resize);

    let lastDraw = 0;
    const draw = (time: number) => {
      raf = window.requestAnimationFrame(draw);
      if (time - lastDraw < 55) return;
      lastDraw = time;

      ctx.fillStyle = 'rgba(5, 10, 18, 0.135)';
      ctx.fillRect(0, 0, width, height);
      ctx.font = `${fontSize}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;

      columns.forEach((y, index) => {
        const glyph = glyphs[Math.floor(Math.random() * glyphs.length)];
        const x = index * fontSize;
        ctx.fillStyle =
          Math.random() > 0.965
            ? 'rgba(0, 240, 255, 0.78)'
            : 'rgba(0, 240, 255, 0.26)';
        ctx.fillText(glyph, x, y);
        columns[index] = y > height + Math.random() * 280 ? -18 : y + fontSize;
      });
    };

    raf = window.requestAnimationFrame(draw);
    return () => {
      window.cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        opacity,
        pointerEvents: 'none',
      }}
    />
  );
}
