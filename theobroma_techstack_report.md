# Theobroma.in — Full Tech Stack Analysis

**URL:** https://theobroma.in/
**Date Analyzed:** 19 May 2026
**Methodology:** HTTP headers analysis + HTML source inspection + Server Timing data

---

## 1. Platform & Backend

| Component | Technology | Details |
|-----------|-----------|---------|
| **E-commerce Platform** | **Shopify** | Powered by Shopify (confirmed via `powered-by: Shopify` header & `Shopify` JS global) |
| **Shopify Store Name** | `theobroma-food-of-the-gods.myshopify.com` | Internal myshopify subdomain |
| **Shop ID** | `52139294884` | Shopify digital wallet ID |
| **Locale** | `en-IN` | English (India) |
| **Currency** | INR (Indian Rupee) | `₹ {{amount_no_decimals}}` format |
| **Backend DB** | Shopify Internal DB | Server-timing shows `db;dur=14` ms query time |
| **Shopify Theme** | **Milatino** (v1.0.1) | Custom theme named "Theobroma Theme", theme ID `137984671996`, role: main |
| **Theme Store ID** | `null` | Custom/bespoke theme, not from Shopify Theme Store |

### Server Timing Breakdown

```
processing;dur=73 (GC collections: 5)
db;dur=14             (database query time: 14ms)
edge;desc="BOM"       (served from Mumbai edge)
asn;desc="24560"      (ASN: 24560 - Tata Communications)
```

---

## 2. Hosting & Infrastructure

| Component | Technology | Details |
|-----------|-----------|---------|
| **CDN / Proxy** | **Cloudflare** | `server: cloudflare`, `CF-RAY` headers present |
| **Edge Location** | BOM (Mumbai, India) | Content delivered from Mumbai edge server |
| **DC Location** | `gcp-asia-southeast1` | Google Cloud Platform (Singapore region) |
| **Protocol** | HTTP/3 (h3) | `Alt-Svc: h3=":443"; ma=86400` |
| **TLS** | HTTPS enforced | HSTS: `max-age=7889238` (~91 days) |
| **Security** | `X-Frame-Options: DENY`, CSP, X-XSS-Protection, X-Content-Type-Options | 
| **HTML Size** | ~260 KB | Initial page payload |
| **Load Time** | ~0.5s | Server response time |

---

## 3. Frontend & UI

| Component | Technology | Details |
|-----------|-----------|---------|
| **CSS Framework** | **Bootstrap** (v3/v4) | `bootstrap.min.css` loaded |
| **Custom CSS** | timber_2.scss, style-main.scss, engo-customize.scss | SCSS compiled to CSS |
| **JavaScript** | **jQuery 3.6.0 / 3.6.1** | Dual version loaded (Google CDN + local) |
| **Carousel/Slider** | **Slick Carousel** | `slick.css`, `slick-theme.css`, `slick.js` |
| **Lightbox** | **Fancybox** | `jquery.fancybox.min.css` |
| **Icons** | Font Awesome 4.7, Themify Icons, Pe-icon-7-stroke | Icon font stacks |
| **Fonts** | Google Fonts: Overlock, Inter, Quattrocento | WebFont loader used |
| **360 Viewer** | three60 | Product 360-degree view |
| **Slider Engine** | Revolution Slider (rs6) | Premium slider, jQuery-based |
| **Responsive** | Yes | Viewport meta, responsive design |
| **Theme Color** | `#7fc9c4` (Teal) | Theme accent color |

---

## 4. Shopify Apps & Integrations

| App | Purpose | Source |
|-----|---------|--------|
| **PageFly** | Page Builder (drag-drop) | `pagefly-page-builder-280` extension |
| **Ryviu** | Product Reviews & Ratings | `ryviu.com/v/static/js/app.js` |
| **Tabs Studio** | Product Description Tabs | `stationmade.com` / `tabs-studio` |
| **Station Tabs** | Tabbed product content | `tabs.stationmade.com` |
| **Zify Products Slider** | Product carousel widget | `zify-products-slider.js` |
| **Nerdy Form Widget** | Custom form builder | `nerdy-forms` |
| **Booster Page Speed** | Page speed optimization | `booster-page-speed-optimizer` |
| **Parcel Panel / Store Locator** | Store locator | `storelocator.metizapps.com` |
| **Synctrack CTA Buttons** | Call-to-action buttons | `synctrack.io/cta-buttons` |
| **CloudOneGalaxy** | Unknown analytics/tracking | `www.cloudonegalaxy.com` |

---

## 5. Analytics & Marketing

| Tool | Type | Identifier |
|------|------|------------|
| **Google Tag Manager** | Tag management | `GTM-KW7PZLB` |
| **Google Analytics** | Web analytics | Via GTM (gtag) |
| **Meta Pixel (Facebook)** | Social tracking | `facebook-domain-verification: wg0bgummogfxspw1nt2rrsunyavorn` |
| **Microsoft Bing UET** | Ads tracking | Tag ID: `137023898` |
| **Twitter** | Social card | `@theobromaindia` |
| **Instagram** | Social link | `@Theobromapatisserie` |
| **YouTube** | Social link | Channel linked in schema |
| **Schema.org** | Structured data | Organization, SiteNavigationElement JSON-LD |

---

## 6. Third-Party Script Domains

```
ajax.googleapis.com        - jQuery CDN
cdnjs.cloudflare.com       - html5shiv polyfill
cdn.shopify.com            - Shopify core assets
fonts.googleapis.com       - Google Fonts
www.cloudonegalaxy.com     - Unknown third-party
storelocator.metizapps.com - Store locator widget
d1ac7owlocyo08.cloudfront.net - CloudFront CDN asset
monorail-edge.shopifysvc.com - Shopify analytics beacon
```

---

## 7. Security Headers

| Header | Value |
|--------|-------|
| `Strict-Transport-Security` | `max-age=7889238` |
| `X-Frame-Options` | `DENY` |
| `X-Content-Type-Options` | `nosniff` |
| `X-XSS-Protection` | `1; mode=block` |
| `Content-Security-Policy` | `block-all-mixed-content; frame-ancestors 'none'; upgrade-insecure-requests` |
| `Referrer-Policy` | `origin` |
| `X-Permitted-Cross-Domain-Policies` | `none` |
| `X-Download-Options` | `noopen` |

---

## 8. Performance Summary

| Metric | Value |
|--------|-------|
| Server Response Time | ~73ms processing |
| DB Query Time | ~14ms |
| Total Server Time | ~87ms |
| HTML Payload | ~260 KB |
| Total Scripts | 47 (external + inline) |
| CDN | Cloudflare + Shopify CDN + Google Fonts |
| HTTP Protocol | HTTP/3 (QUIC) |
| Compression | Level 5 (Shopify edge compression) |

---

## 9. Key Takeaways

1. **Theobroma runs entirely on Shopify** — no custom backend. All products, orders, and customer data live in Shopify's infrastructure.
2. **Cloudflare** sits in front as CDN + security proxy, with edge node in Mumbai (BOM).
3. **Backend servers** are on Google Cloud Platform (asia-southeast1, Singapore).
4. **Theme is custom-built** ("Milatino" schema, named "Theobroma Theme") — not a public Shopify theme.
5. **Heavy use of page builder** (PageFly) for landing pages and custom layouts.
6. **47 external scripts** loaded — moderate bloat from apps (reviews, tabs, sliders, forms, tracking).
7. **No React/Vue/Angular** — pure jQuery-based frontend with Bootstrap 3/4.
8. **Database queries are fast** (14ms) — likely due to Shopify's internal caching + Cloudflare.

---

*Report generated by WA-Bot analysis tool*
