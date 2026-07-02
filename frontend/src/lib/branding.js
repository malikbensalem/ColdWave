// White-label branding helpers: convert a hex colour to the HSL triplet Tailwind
// expects (hsl(var(--primary))) and apply it to the document root.

export function hexToHslTriplet(hex) {
  if (!hex) return null;
  let h = hex.replace("#", "").trim();
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  if (h.length !== 6) return null;
  const r = parseInt(h.slice(0, 2), 16) / 255;
  const g = parseInt(h.slice(2, 4), 16) / 255;
  const b = parseInt(h.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let hue = 0, sat = 0;
  const light = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    sat = light > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: hue = (g - b) / d + (g < b ? 6 : 0); break;
      case g: hue = (b - r) / d + 2; break;
      default: hue = (r - g) / d + 4;
    }
    hue /= 6;
  }
  return `${Math.round(hue * 360)} ${Math.round(sat * 100)}% ${Math.round(light * 100)}%`;
}

export function applyPrimaryColor(hex) {
  const root = document.documentElement;
  const triplet = hexToHslTriplet(hex);
  if (triplet) {
    root.style.setProperty("--primary", triplet);
    root.style.setProperty("--ring", triplet);
    root.style.setProperty("--sidebar-primary", triplet);
  } else {
    root.style.removeProperty("--primary");
    root.style.removeProperty("--ring");
    root.style.removeProperty("--sidebar-primary");
  }
}

export function applyBranding(branding) {
  if (!branding) return;
  applyPrimaryColor(branding.primary_color);
  if (branding.brand_name) document.title = `${branding.brand_name} · Powered by ColdWave`;
  else document.title = "ColdWave · AI Cold Calling";
  // Notify React consumers (e.g. Layout sidebar) so brand name/logo update without a reload.
  try { window.dispatchEvent(new CustomEvent("coldwave:branding", { detail: branding })); } catch { /* noop */ }
}
