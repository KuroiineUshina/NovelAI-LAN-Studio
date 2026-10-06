import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Brush, Eraser, FlipHorizontal2, Trash2, Undo2 } from "lucide-react";

export interface InpaintCanvasHandle {
  exportMask: () => Promise<Blob>;
  hasMask: () => boolean;
}

interface Props {
  sourceUrl: string;
}

export const InpaintCanvas = forwardRef<InpaintCanvasHandle, Props>(function InpaintCanvas(
  { sourceUrl },
  ref,
) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const drawingRef = useRef(false);
  const historyRef = useRef<string[]>([]);
  const [brushSize, setBrushSize] = useState(64);
  const [eraser, setEraser] = useState(false);
  const [inverted, setInverted] = useState(false);
  const [hasPaint, setHasPaint] = useState(false);
  const [ready, setReady] = useState(false);

  const snapshot = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    historyRef.current = [...historyRef.current.slice(-19), canvas.toDataURL("image/png")];
  };

  const clear = () => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    context.clearRect(0, 0, canvas.width, canvas.height);
    historyRef.current = [canvas.toDataURL("image/png")];
    setHasPaint(false);
  };

  useEffect(() => {
    setReady(false);
    setInverted(false);
    setHasPaint(false);
    historyRef.current = [];
  }, [sourceUrl]);

  const handleImageLoad = () => {
    const image = imageRef.current;
    const canvas = canvasRef.current;
    if (!image || !canvas) return;
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    clear();
    setReady(true);
  };

  const point = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((event.clientX - rect.left) / rect.width) * canvas.width,
      y: ((event.clientY - rect.top) / rect.height) * canvas.height,
    };
  };

  const startDrawing = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!ready) return;
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    canvas.setPointerCapture(event.pointerId);
    drawingRef.current = true;
    const current = point(event);
    context.beginPath();
    context.moveTo(current.x, current.y);
    context.lineCap = "round";
    context.lineJoin = "round";
    context.lineWidth = brushSize;
    context.strokeStyle = "#ffffff";
    context.globalCompositeOperation = eraser ? "destination-out" : "source-over";
    context.lineTo(current.x + 0.1, current.y + 0.1);
    context.stroke();
  };

  const draw = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current) return;
    const context = canvasRef.current?.getContext("2d");
    if (!context) return;
    const current = point(event);
    context.lineTo(current.x, current.y);
    context.stroke();
  };

  const endDrawing = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current) return;
    drawingRef.current = false;
    canvasRef.current?.releasePointerCapture(event.pointerId);
    snapshot();
    if (!eraser) setHasPaint(true);
  };

  const undo = () => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context || historyRef.current.length <= 1) return;
    historyRef.current.pop();
    const previous = historyRef.current.at(-1);
    if (!previous) return;
    const image = new Image();
    image.onload = () => {
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.globalCompositeOperation = "source-over";
      context.drawImage(image, 0, 0);
      setHasPaint(historyRef.current.length > 1);
    };
    image.src = previous;
  };

  useImperativeHandle(ref, () => ({
    hasMask: () => hasPaint || inverted,
    exportMask: () =>
      new Promise<Blob>((resolve, reject) => {
        const source = canvasRef.current;
        if (!source) {
          reject(new Error("마스크를 준비하지 못했어요"));
          return;
        }
        const output = document.createElement("canvas");
        output.width = source.width;
        output.height = source.height;
        const context = output.getContext("2d");
        if (!context) {
          reject(new Error("마스크를 만들지 못했어요"));
          return;
        }
        if (inverted) {
          context.fillStyle = "white";
          context.fillRect(0, 0, output.width, output.height);
          context.globalCompositeOperation = "destination-out";
          context.drawImage(source, 0, 0);
          context.globalCompositeOperation = "destination-over";
          context.fillStyle = "black";
          context.fillRect(0, 0, output.width, output.height);
        } else {
          context.fillStyle = "black";
          context.fillRect(0, 0, output.width, output.height);
          context.drawImage(source, 0, 0);
        }
        output.toBlob((blob) => {
          if (blob) resolve(blob);
          else reject(new Error("마스크를 만들지 못했어요"));
        }, "image/png");
      }),
  }), [hasPaint, inverted]);

  return (
    <section className="panel inpaint-panel" aria-label="인페인트 마스크 편집기">
      <div className="inpaint-toolbar">
        <label className="inpaint-brush">
          <span>브러시</span>
          <input
            type="range"
            min="8"
            max="320"
            value={brushSize}
            onChange={(event) => setBrushSize(Number(event.target.value))}
            aria-label="브러시 크기"
          />
          <output className="counter">{brushSize}px</output>
        </label>
        <div className="segmented inpaint-tools">
          <button type="button" aria-pressed={!eraser} onClick={() => setEraser(false)}><Brush aria-hidden="true" />칠하기</button>
          <button type="button" aria-pressed={eraser} onClick={() => setEraser(true)}><Eraser aria-hidden="true" />지우개</button>
        </div>
        <button type="button" className={inverted ? "button small active-toggle" : "button small"} aria-pressed={inverted} onClick={() => setInverted((value) => !value)}>
          <FlipHorizontal2 aria-hidden="true" />반전
        </button>
        <div className="inpaint-history">
          <button type="button" className="icon-button small" onClick={undo} disabled={historyRef.current.length <= 1} aria-label="실행 취소" title="실행 취소"><Undo2 aria-hidden="true" /></button>
          <button type="button" className="icon-button small danger" onClick={clear} aria-label="마스크 지우기" title="마스크 지우기"><Trash2 aria-hidden="true" /></button>
        </div>
      </div>
      <div className="inpaint-stage">
        <img ref={imageRef} src={sourceUrl} alt="인페인트 원본" onLoad={handleImageLoad} draggable={false} />
        <canvas
          ref={canvasRef}
          className={inverted ? "mask-canvas inverted" : "mask-canvas"}
          onPointerDown={startDrawing}
          onPointerMove={draw}
          onPointerUp={endDrawing}
          onPointerCancel={endDrawing}
          aria-label="마스크 그리기 영역"
        />
      </div>
    </section>
  );
});
