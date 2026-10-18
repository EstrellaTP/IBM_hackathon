/**
 * Brand mark: a teal square with a pulse line, followed by the product name.
 *
 * @module brand
 */

import { BRAND_NAME } from "./config.js";

const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * Build the brand element.
 *
 * @returns {HTMLSpanElement} Mark and name.
 */
export function brandElement() {
  const brand = document.createElement("span");
  brand.className = "brand";
  const mark = document.createElement("span");
  mark.className = "brand__mark";
  mark.setAttribute("aria-hidden", "true");
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", "M1 9h3l2-4 3 7 2-4h4");
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "#ffffff");
  path.setAttribute("stroke-width", "1.6");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  svg.append(path);
  mark.append(svg);
  brand.append(mark, document.createTextNode(BRAND_NAME));
  return brand;
}
