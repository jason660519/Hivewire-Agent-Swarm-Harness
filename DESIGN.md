---
name: Hivewire Operations Console Design System
version: 0.1.0
colors:
  primary: "#06b6d4"       # Cyber Cyan accent for logos, links, glows
  neutral: "#e6edf6"       # Primary text color (high contrast ink)
  neutral-muted: "#8896ab" # Secondary text color (low contrast ink)
  neutral-dim: "#aeb9c9"   # Intermediate descriptive text
  bg-dark: "#070a13"       # Deep outer-space background canvas
  bg-panel: "rgba(13, 20, 32, 0.7)" # Glassy translucent slate for widgets
  bg-active: "rgba(31, 41, 55, 0.85)" # Selected state backgrounds
  border: "rgba(255, 255, 255, 0.08)" # Soft borders separating widgets
  border-active: "rgba(255, 255, 255, 0.15)" # Focused borders
  success: "#10b981"       # Emerald green for active, healthy, and successful states
  warning: "#f59e0b"       # Amber yellow/orange for warnings and blocked states
  error: "#f43f5e"         # Rose red for failures and alerts
typography:
  fontFamily:
    sans: "Inter, system-ui, -apple-system, BlinkMacSystemFont, sans-serif"
    mono: "JetBrains Mono, monospace"
  body:
    fontSize: "13px"
    fontFamily: "{typography.fontFamily.sans}"
  code:
    fontSize: "11px"
    fontFamily: "{typography.fontFamily.mono}"
  logo:
    fontSize: "14px"
    fontWeight: "700"
    fontFamily: "{typography.fontFamily.sans}"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
shapes:
  borderRadius: "6px"
  borderRadiusLarge: "8px"
  borderRadiusPill: "99px"
components:
  panel:
    background: "{colors.bg-panel}"
    border: "1px solid {colors.border}"
    borderRadius: "{shapes.borderRadiusLarge}"
  button:
    fontSize: "{typography.body.fontSize}"
    borderRadius: "{shapes.borderRadius}"
    padding: "6px 12px"
---

## Overview

The Hivewire Operations Console design language is engineered for the system operator—providing a high-density, professional, and visually stunning observability platform. The aesthetic, dubbed **Cybernetic Observability**, utilizes a dark cyber-grid canvas with vibrant radial color glows (using our primary Cyber Cyan). The interface prioritizes real-time data streaming, latency comparison, and direct control without feeling cluttered. 

It avoids generic styling and uses a tailored color-coded role mapping for quick visual triage: emerald for health, amber for warnings, and rose for errors.

## Colors

The color palette is built for a dark-mode-first console application:
- **Primary Ink & Canvas**: The background is a very deep slate-blue `#070a13` (`colors.bg-dark`) overlayed with subtle cyan radial gradients (`rgba(6, 182, 212, 0.05)`). Headlines and main texts use `#e6edf6` (`colors.neutral`) to ensure AAA WCAG accessibility contrast.
- **Accents**: Our primary branding accent is Cyber Cyan `#06b6d4` (`colors.primary`), which is used sparingly for active states, link borders, logos, and critical route pathways.
- **Semantic State Mapping**: 
  - **Success**: `#10b981` (`colors.success`) for successfully routed request events and online status indicators.
  - **Warning / Blocked**: `#f59e0b` (`colors.warning`) for blocked/rate-limited endpoints or warning messages.
  - **Error**: `#f43f5e` (`colors.error`) for failed connections or critical CLI/Linter alert states.

## Typography

The interface employs two specific typeface roles:
- **Inter**: The main UI font, offering exceptional legibility for high-density tabular and card data. Font sizes range from 9px for tiny labels/metadata, to 13px for general body/labels, and 14px for brand headings.
- **JetBrains Mono**: The monospace system font reserved for developer-centric telemetry data—including IP addresses, latency timings, cost calculations, payload logs, and code diff output.

## Layout

The screen layout is divided into a three-pane layout using modern flex and grid configurations:
- **Density**: Maximized for professional viewing. Spacings use `{spacing.sm}` (8px) for card interiors and `{spacing.lg}` (16px) for panel gaps.
- **Glassmorphism**: Panels and overlays use `{colors.bg-panel}` combined with `backdrop-filter: blur(12px)` and a soft border `{colors.border}` to give a sense of depth over the cyan background glows.

## Elevation & Depth

No physical drop shadows are used on standard components to preserve the clean, neon-hud aesthetic. Instead:
- Depth is simulated using layering and transparency (`backdrop-filter`).
- Active hover states on interactive cards use a cyan shadow filter `drop-shadow(0 0 4px {colors.primary})` and an increased border opacity (`{colors.border-active}`).

## Shapes

To balance the technical, command-line nature of the tool with modern visual trends:
- Container panels use `{shapes.borderRadiusLarge}` (8px) for a soft framing effect.
- Active states, code blocks, buttons, and individual timeline cards use `{shapes.borderRadius}` (6px).
- Badges and status indicators use `{shapes.borderRadiusPill}` (99px).

## Components

The system features several custom observability components:
- **Timeline Event Cards**: Border-left colored according to the semantic state (Emerald, Amber, Rose) with a `{colors.bg-panel}` background. On hover, they slide up by `2px` and brighten their borders.
- **Bottom Command Composer**: A dark command entry container (`#09111d`) featuring a responsive grid layout mapping controls, a monospace entry field, and call-to-action buttons using `{components.button}` specs.
- **Route Map Visualization SVG**: Clean nodes drawn with `{colors.border}` outlines and active nodes using `{colors.primary}` with glow drop-shadow filters.
