// import { GitHubLogoIcon } from "@radix-ui/react-icons";

import { AuroraText } from "@/components/ui/aurora-text";
// import { Button } from "@/components/ui/button";
import { useAppConfig } from "@/core/config";

import { Section } from "../section";

export function CommunitySection() {
  const { brand } = useAppConfig();
  // const githubUrl = brand.github_url ?? "https://github.com/thinktank-ai/thinktank-ai";

  return (
    <Section
      title={
        <AuroraText colors={["#60A5FA", "#A5FA60", "#A560FA"]}>
          Back the Vision
        </AuroraText>
      }
      subtitle={`We're raising to scale ${brand.name} into the default AI operating layer for ambitious teams. If you're an investor, we'd love to share our traction and roadmap.`}
    >
      {null}
      {/* <div className="flex justify-center">
        <Button className="text-xl" size="lg" asChild>
          <a href={githubUrl} target="_blank" rel="noopener noreferrer">
            <GitHubLogoIcon />
            Review Our Traction
          </a>
        </Button>
      </div> */}
    </Section>
  );
}
