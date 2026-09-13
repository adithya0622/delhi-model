import { forwardRef } from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Button — shadcn-idiom (CVA + cn + forwardRef), but mapped onto the ported
 * `.btn` design classes rather than re-styled with utilities, so it stays
 * pixel-consistent with the rest of the instrument.
 */
const buttonVariants = cva("btn", {
  variants: {
    variant: {
      ghost: "",
      solid: "btn--solid",
    },
  },
  defaultVariants: { variant: "ghost" },
});

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, type, ...props }, ref) => (
    <button
      ref={ref}
      type={type ?? "button"}
      className={cn(buttonVariants({ variant }), className)}
      {...props}
    />
  ),
);
Button.displayName = "Button";

export { buttonVariants };
