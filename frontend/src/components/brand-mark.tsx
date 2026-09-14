"use client";

import Link from "next/link";

import { useBrand } from "@/components/brand-provider";
import { cn } from "@/lib/utils";

type BrandMarkProps = {
  href?: string;
  className?: string;
  size?: "sm" | "lg";
};

export function BrandMark({
  href = "/",
  className,
  size = "lg",
}: BrandMarkProps) {
  const { config } = useBrand();
  const { name, product } = config.brand;

  const content = (
    <span
      className={cn(
        "font-heading font-semibold tracking-tight",
        size === "lg" && "text-3xl sm:text-4xl",
        size === "sm" && "text-lg",
        className,
      )}
    >
      <span className="brand-text-gradient">{name}</span>
      <span className="text-foreground/90"> {product}</span>
    </span>
  );

  if (href) {
    return (
      <Link href={href} className="inline-block">
        {content}
      </Link>
    );
  }
  return content;
}
