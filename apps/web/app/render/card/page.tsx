"use client";

/**
 * One card on its own, for the worker's headless browser (task 0045): designer_toad sees its
 * art on the real card at a phone's width, as a reader will. The worker hands the card in
 * through `window.spoinRenderCard`, so the page calls no API and shows nothing until then.
 */

import { useEffect, useState } from "react";
import { MotionConfig } from "framer-motion";

import { topicHue } from "@/lib/topicColor";
import type { Card as CardModel } from "@/lib/api";
import { Card } from "@/components/Card";

interface Shown {
  card: CardModel;
  topicName: string;
}

declare global {
  interface Window {
    spoinRenderCard?: (shown: Shown) => void;
  }
}

function ignore() {}

export default function RenderCardPage() {
  const [shown, setShown] = useState<Shown | null>(null);

  useEffect(() => {
    window.spoinRenderCard = setShown;
    return () => {
      delete window.spoinRenderCard;
    };
  }, []);

  if (!shown) return null;
  return (
    // Still frames: a screenshot taken mid-animation would judge the art by a blur.
    <MotionConfig reducedMotion="always">
      <div className="shell">
        <main className="track">
          <div data-rendered-card={shown.card.id}>
            <Card
              card={shown.card}
              topicName={shown.topicName}
              accentHue={topicHue(shown.card.topic_id, undefined)}
              seen={false}
              onSeen={ignore}
              onUnseen={ignore}
              isHero={shown.card.is_hero}
            />
          </div>
        </main>
      </div>
    </MotionConfig>
  );
}
