import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";

type DetailMotion = "previous" | "next" | null;

interface Props {
  src: string;
  alt: string;
  motion: DetailMotion;
  position: number;
  total: number;
  canPrevious: boolean;
  canNext: boolean;
  navigating: boolean;
  onNavigate: (direction: -1 | 1) => void;
  onExitZoom: () => void;
  onSwipeClose: () => void;
}

interface ViewTransform {
  scale: number;
  x: number;
  y: number;
  dragX: number;
  dragY: number;
}

interface Point {
  x: number;
  y: number;
}

const FIT_SCALE_EPSILON = 1.01;
const MAX_SCALE = 5;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function distance(first: Point, second: Point): number {
  return Math.hypot(first.x - second.x, first.y - second.y);
}

const FIT_TRANSFORM: ViewTransform = { scale: 1, x: 0, y: 0, dragX: 0, dragY: 0 };

export function ZoomableGalleryImage({
  src,
  alt,
  motion,
  position,
  total,
  canPrevious,
  canNext,
  navigating,
  onNavigate,
  onExitZoom,
  onSwipeClose,
}: Props) {
  const stageRef = useRef<HTMLDivElement>(null);
  const transformRef = useRef<ViewTransform>({ ...FIT_TRANSFORM });
  const pointers = useRef(new Map<number, Point>());
  const singleStart = useRef<Point | null>(null);
  const panLast = useRef<Point | null>(null);
  const pinchStart = useRef<{ distance: number; scale: number } | null>(null);
  const [transform, setTransformState] = useState<ViewTransform>({ ...FIT_TRANSFORM });

  const setTransform = useCallback((next: ViewTransform) => {
    transformRef.current = next;
    setTransformState(next);
  }, []);

  const resetToFit = useCallback(() => {
    pointers.current.clear();
    singleStart.current = null;
    panLast.current = null;
    pinchStart.current = null;
    setTransform({ ...FIT_TRANSFORM });
  }, [setTransform]);

  useEffect(() => {
    resetToFit();
  }, [resetToFit, src]);

  const currentPoints = () => Array.from(pointers.current.values());

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const points = currentPoints();
    if (points.length === 1) {
      singleStart.current = { ...points[0] };
      panLast.current = { ...points[0] };
      setTransform({ ...transformRef.current, dragX: 0, dragY: 0 });
    } else if (points.length === 2) {
      pinchStart.current = {
        distance: Math.max(1, distance(points[0], points[1])),
        scale: transformRef.current.scale,
      };
      singleStart.current = null;
      setTransform({ ...transformRef.current, dragX: 0, dragY: 0 });
    }
    event.preventDefault();
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!pointers.current.has(event.pointerId)) return;
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const points = currentPoints();
    const current = transformRef.current;
    if (points.length >= 2) {
      const start = pinchStart.current ?? {
        distance: Math.max(1, distance(points[0], points[1])),
        scale: current.scale,
      };
      pinchStart.current = start;
      let scale = clamp(
        start.scale * distance(points[0], points[1]) / start.distance,
        1,
        MAX_SCALE,
      );
      if (scale < 1.03) scale = 1;
      setTransform({
        scale,
        x: scale === 1 ? 0 : current.x,
        y: scale === 1 ? 0 : current.y,
        dragX: 0,
        dragY: 0,
      });
    } else if (points.length === 1) {
      const point = points[0];
      if (current.scale > FIT_SCALE_EPSILON && panLast.current) {
        const stage = stageRef.current;
        const maximumX = (stage?.clientWidth ?? 0) * (current.scale - 1) / 2;
        const maximumY = (stage?.clientHeight ?? 0) * (current.scale - 1) / 2;
        setTransform({
          ...current,
          x: clamp(current.x + point.x - panLast.current.x, -maximumX, maximumX),
          y: clamp(current.y + point.y - panLast.current.y, -maximumY, maximumY),
          dragX: 0,
          dragY: 0,
        });
        panLast.current = { ...point };
      } else if (singleStart.current) {
        setTransform({
          ...current,
          dragX: point.x - singleStart.current.x,
          dragY: point.y - singleStart.current.y,
        });
      }
    }
    event.preventDefault();
  };

  const finishPointer = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!pointers.current.has(event.pointerId)) return;
    pointers.current.delete(event.pointerId);
    const remaining = currentPoints();
    if (remaining.length === 1) {
      panLast.current = { ...remaining[0] };
      singleStart.current = null;
    } else if (!remaining.length) {
      const current = transformRef.current;
      if (current.scale <= FIT_SCALE_EPSILON && singleStart.current) {
        const deltaX = current.dragX;
        const deltaY = current.dragY;
        if (deltaY > 110 && Math.abs(deltaY) > Math.abs(deltaX) * 1.12) {
          resetToFit();
          onSwipeClose();
          return;
        }
        if (Math.abs(deltaX) > 70 && Math.abs(deltaX) > Math.abs(deltaY) * 1.15) {
          resetToFit();
          onNavigate(deltaX < 0 ? 1 : -1);
          return;
        }
      }
      singleStart.current = null;
      panLast.current = null;
      pinchStart.current = null;
      setTransform({ ...current, dragX: 0, dragY: 0 });
    }
    event.preventDefault();
  };

  const handleDoubleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (transformRef.current.scale > FIT_SCALE_EPSILON) {
      resetToFit();
    } else {
      setTransform({ scale: 2.5, x: 0, y: 0, dragX: 0, dragY: 0 });
    }
    event.preventDefault();
  };

  const handleWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    let scale = clamp(transformRef.current.scale - event.deltaY * 0.002, 1, MAX_SCALE);
    if (scale < 1.03) scale = 1;
    setTransform({
      ...transformRef.current,
      scale,
      x: scale === 1 ? 0 : transformRef.current.x,
      y: scale === 1 ? 0 : transformRef.current.y,
      dragX: 0,
      dragY: 0,
    });
    event.preventDefault();
  };

  const fitted = transform.scale <= FIT_SCALE_EPSILON;
  const translatedX = transform.x + transform.dragX;
  const translatedY = transform.y + transform.dragY;

  return (
    <div className={fitted ? "zoom-backdrop" : "zoom-backdrop image-zoomed"} role="dialog" aria-modal="true" aria-label="원본 이미지 전체화면 보기">
      <button type="button" className="zoom-close" onClick={onExitZoom} aria-label="전체화면 보기 닫기"><X aria-hidden="true" strokeWidth={1.8} /></button>
      <button type="button" className="zoom-nav previous" onClick={() => onNavigate(-1)} disabled={!fitted || !canPrevious || navigating} aria-label="이전 이미지"><ChevronLeft aria-hidden="true" strokeWidth={1.8} /></button>
      <div
        ref={stageRef}
        className="zoom-image-stage gesture-stage"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishPointer}
        onPointerCancel={finishPointer}
        onDoubleClick={handleDoubleClick}
        onWheel={handleWheel}
      >
        <div className={["zoom-image-frame", motion ? `navigate-${motion}` : ""].filter(Boolean).join(" ")}>
          <img
            src={src}
            alt={alt}
            className="gesture-image"
            draggable={false}
            style={{ transform: `translate3d(${translatedX}px, ${translatedY}px, 0) scale(${transform.scale})` }}
          />
        </div>
      </div>
      <button type="button" className="zoom-nav next" onClick={() => onNavigate(1)} disabled={!fitted || !canNext || navigating} aria-label="다음 이미지"><ChevronRight aria-hidden="true" strokeWidth={1.8} /></button>
      <div className="zoom-caption">
        <span>{position} / {total}</span>
        {fitted ? null : <span className="zoom-scale">{transform.scale.toFixed(1)}×</span>}
      </div>
    </div>
  );
}
