import os

foldtext_code = r"""import React, { useEffect, useMemo, useRef } from 'react';
import { gsap } from 'gsap';
import './FoldText.css';

export type SplitBy = 'char' | 'word' | 'line';
export type Hinge = 'top' | 'bottom' | 'left' | 'right';
export type Trigger = 'mount' | 'hover' | 'scroll' | 'loop';

export interface FoldTextProps {
  text?: string;
  splitBy?: SplitBy;
  hinge?: Hinge;
  duration?: number;
  stagger?: number;
  ease?: string;
  perspective?: number;
  creaseShading?: number;
  trigger?: Trigger;
  fontSize?: string | number;
  fontWeight?: string | number;
  color?: string;
  className?: string;
  style?: React.CSSProperties;
  onComplete?: () => void;
}

const HINGE_CONFIG: Record<Hinge, { origin: string; rotateX: number; rotateY: number }> = {
  top: { origin: '50% 0%', rotateX: -92, rotateY: 0 },
  bottom: { origin: '50% 100%', rotateX: 92, rotateY: 0 },
  left: { origin: '0% 50%', rotateX: 0, rotateY: 92 },
  right: { origin: '100% 50%', rotateX: 0, rotateY: -92 }
};

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

export const FoldText: React.FC<FoldTextProps> = ({
  text = 'Lets Decode The Atmosphere',
  splitBy = 'char',
  hinge = 'top',
  duration = 0.65,
  stagger = 0.04,
  ease = 'power3.out',
  perspective = 700,
  creaseShading = 0.55,
  trigger = 'mount',
  fontSize = 'clamp(2.4rem, 6vw, 4.6rem)',
  fontWeight = 800,
  color = '#FFFFFF',
  className = '',
  style = {},
  onComplete
}) => {
  const rootRef = useRef<HTMLSpanElement>(null);
  const onCompleteRef = useRef(onComplete);

  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  const hingeConfig = HINGE_CONFIG[hinge] || HINGE_CONFIG.top;
  const safeCrease = clamp(creaseShading, 0, 1);
  const safePerspective = Math.max(120, perspective);

  const segments = useMemo(() => {
    let segmentIndex = 0;

    const renderSegment = (content: React.ReactNode, key: string, split: SplitBy = splitBy) => {
      segmentIndex += 1;
      return (
        <span
          className="fold-text-segment"
          data-fold-split={split}
          key={key}
          style={{ '--fold-perspective': `${safePerspective}px` } as React.CSSProperties}
        >
          <span
            className="fold-text-piece"
            data-fold-hinge={hinge}
            style={{ transformOrigin: hingeConfig.origin, '--fold-crease': 0 } as React.CSSProperties}
          >
            {content || '\u00A0'}
          </span>
        </span>
      );
    };

    if (splitBy === 'line') {
      return text.split('\n').map((line, index) => (
        <span className="fold-text-line" key={`line-${index}`}>
          {renderSegment(line || '\u00A0', `segment-line-${index}`, 'line')}
        </span>
      ));
    }

    if (splitBy === 'word') {
      return text.split(/(\s+)/).flatMap((part, index) => {
        if (!part) return [];
        if (/^\s+$/.test(part)) {
          return (
            <span className="fold-text-whitespace" key={`ws-${index}`}>
              {part.replace(/ /g, '\u00A0')}
            </span>
          );
        }
        return renderSegment(part, `segment-word-${segmentIndex}`);
      });
    }

    return Array.from(text).map((char, index) => {
      if (char === '\n') return <br key={`br-${index}`} />;
      return renderSegment(char === ' ' ? '\u00A0' : char, `segment-char-${index}`);
    });
  }, [text, splitBy, hinge, hingeConfig.origin, safePerspective]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    const ctx = gsap.context(() => {
      const pieces = root.querySelectorAll('.fold-text-piece');
      if (!pieces || pieces.length === 0) return;

      const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      const activeDuration = reduceMotion ? Math.min(duration, 0.22) : duration;
      const activeStagger = reduceMotion ? Math.min(stagger, 0.02) : stagger;

      const tl = gsap.timeline({
        repeat: trigger === 'loop' ? -1 : 0,
        repeatDelay: trigger === 'loop' ? 0.75 : 0,
        onComplete: () => {
          if (onCompleteRef.current) {
            onCompleteRef.current();
          }
        }
      });

      tl.fromTo(
        pieces,
        {
          opacity: 0,
          rotateX: reduceMotion ? 0 : hingeConfig.rotateX,
          rotateY: reduceMotion ? 0 : hingeConfig.rotateY,
          '--fold-crease': reduceMotion ? 0 : safeCrease,
          transformOrigin: hingeConfig.origin,
          force3D: true
        },
        {
          opacity: 1,
          rotateX: 0,
          rotateY: 0,
          '--fold-crease': 0,
          duration: activeDuration,
          ease: ease,
          stagger: activeStagger,
          clearProps: 'willChange'
        }
      );
    }, rootRef);

    return () => {
      ctx.revert();
    };
  }, [text, splitBy, hinge, duration, stagger, ease, safeCrease, trigger, hingeConfig.origin, hingeConfig.rotateX, hingeConfig.rotateY]);

  const rootStyle = {
    '--fold-text-font-size': typeof fontSize === 'number' ? `${fontSize}px` : fontSize,
    '--fold-text-font-weight': fontWeight,
    '--fold-text-color': color,
    ...style
  };

  return (
    <span ref={rootRef} className={`fold-text ${className}`.trim()} style={rootStyle}>
      <span className="fold-text-sr-only">{text}</span>
      <span className="fold-text-visual" aria-hidden="true">
        {segments}
      </span>
    </span>
  );
};

export default FoldText;
"""

with open("webapp/src/components/ui/FoldText.tsx", "w", encoding="utf-8") as f:
    f.write(foldtext_code)

print("FoldText.tsx successfully written with gsap.context!")
