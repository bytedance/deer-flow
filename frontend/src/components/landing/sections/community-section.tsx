"use client";

import { GitHubLogoIcon } from "@radix-ui/react-icons";
import Link from "next/link";

import { AuroraText } from "@/components/ui/aurora-text";
import { Button } from "@/components/ui/button";

import { Section } from "../section";

export function CommunitySection() {
  return (
    <Section
      title={
        <AuroraText colors={["#60A5FA", "#A5FA60", "#A560FA"]}>
          Join the Community
        </AuroraText>
      }
      subtitle="Contribute brilliant ideas to shape the future of DeerFlow. Collaborate, innovate, and make impacts."
    >
      <div className="flex justify-center">
        <Button className="text-xl" size="lg" asChild>
          <Link href="https://github.com/bytedance/deer-flow" target="_blank">
            <GitHubLogoIcon />
            Contribute Now
          </Link>
        </Button>
      </div>
    </Section>
  );
}
