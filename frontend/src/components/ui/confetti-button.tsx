"use client";

import React, { type MouseEventHandler } from "react";
import confetti from "canvas-confetti";

import { Button } from "@/components/ui/button";

interface ConfettiButtonProps extends React.ComponentProps<typeof Button> {
  angle?: number;
  particleCount?: number;
  startVelocity?: number;
  spread?: number;
  onClick?: MouseEventHandler<HTMLButtonElement>;
}

export function ConfettiButton({
  className,
  children,
  angle = 90,
  particleCount = 75,
  startVelocity = 35,
  spread = 70,
  onClick,
  ...props
}: ConfettiButtonProps) {
  const handleClick: MouseEventHandler<HTMLButtonElement> = (event) => {
    const target = event.currentTarget;
    if (target) {
      const rect = target.getBoundingClientRect();
      confetti({
        particleCount,
        startVelocity,
        angle,
        spread,
        origin: {
          x: (rect.left + rect.width / 2) / window.innerWidth,
          y: (rect.top + rect.height / 2) / window.innerHeight,
        },
      });
    }
    onClick?.(event);
  };

  return (
    <Button onClick={handleClick} className={className} {...props}>
      {children}
    </Button>
  );
}
