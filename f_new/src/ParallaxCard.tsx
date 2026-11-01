import { useEffect, useRef, type PointerEvent } from "react";
import { Leaf } from "lucide-react";

interface ParallaxCardProps {
  pill: string;
  index: string;
  title: string;
  description: string;
  image: string;
  caption: string;
}

export default function ParallaxCard({ pill, index, title, description, image, caption }: ParallaxCardProps) {
  const cardRef = useRef<HTMLElement>(null);
  const reducedMotion = useRef(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    reducedMotion.current = query.matches;
    const update = (event: MediaQueryListEvent) => { reducedMotion.current = event.matches; };
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  const move = (event: PointerEvent<HTMLElement>) => {
    if (reducedMotion.current || event.pointerType === "touch" || !cardRef.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    cardRef.current.style.setProperty("--rx", `${(0.5 - (event.clientY - rect.top) / rect.height) * 3}deg`);
    cardRef.current.style.setProperty("--ry", `${((event.clientX - rect.left) / rect.width - 0.5) * 3}deg`);
  };

  const reset = () => {
    cardRef.current?.style.setProperty("--rx", "0deg");
    cardRef.current?.style.setProperty("--ry", "0deg");
  };

  return (
    <article ref={cardRef} className="nature-card" onPointerMove={move} onPointerLeave={reset}>
      <div className="nature-card-top"><span>{pill}</span><span>{index} / 03</span></div>
      <h3>{title}</h3>
      <p>{description}</p>
      <figure className="nature-scene">
        <img src={image} alt="" loading="lazy" width={1200} height={800} />
        <figcaption><span>{caption}</span><Leaf size={16} strokeWidth={1.4} aria-hidden="true" /></figcaption>
      </figure>
    </article>
  );
}
