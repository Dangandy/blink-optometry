# Blink Optometry — Phoropter Exam Landing Page

## Concept
The landing page opens as a simulated eye exam from the patient's POV:
the page loads blurred, a vintage black-and-brass phoropter descends,
the camera pushes into one lens, the hero "clicks" into focus, and the
lens rim then persists as a circular overlay while the user scrolls the
real site normally. The exam metaphor = "we make things clear."

## Assets (in /assets, provided — do not regenerate)
- `frame1_page_blurred.png` — full page on white wall, heavily blurred, no device
- `frame2_descend_end.png` — phoropter descended over blurred page (wide)
- `frame3_pushin_start.png` — two-lens close-up, hero sharp in right lens, no occluder
- `frame4_lens_blurred.png` — single lens fills frame, hero BLURRED inside
- `frame5_lens_sharp.png` — identical framing, hero SHARP inside (focus click pair)
- `rim_raw.png` — lens rim on white; center must be masked/knocked out to
  transparent to create `rim_overlay.png` (build step, script it)
- Video clips (added later, after site is approved):
  - `clip1_descend.mp4` — frame1 → frame2 motion (~4s)
  - `clip2_pushin.mp4` — frame3 → frame4 motion (~4s)

## Real content (source of truth: blinkvision.ca)
- Logo: teal eye icon. Heading: BLINK
- Subheading: Vision Care • Contact Lens • Myopia Control
- CTA: Book Appointment → https://www.blinkvision.ca/book-now
- Hours: Mon 10am–6pm / Tue Closed / Wed 11am–7pm / Thu 12pm–7pm /
  Fri 11am–7pm / Sat 9am–3pm / Sun By Appointment Only
- Address: 4236 Sheppard Ave. East, Unit 75, Scarborough, ON M1S 2C1
- Tel: 416-292-9750 · Email: info@blinkvision.ca
- Services (for a services section): Comprehensive Eye Exams, Contact Lens
  (Soft & Specialty), Myopia Control / Ortho-K, Paediatric Eye Exam,
  Diabetic Eye Exam, Laser Eye Surgery consult
- Accent color: teal (sample exact hex from frame3). Clean, warm, family tone.

## Phase 1 — Site scaffold (stills only, no video yet)
1. Static site, vanilla HTML/CSS/JS (no framework needed). Mobile-first,
   portrait-oriented hero; desktop letterboxes the porthole gracefully.
2. Build the real page: hero matched to frame5 (same logo lockup, same
   button proportions), then Services, Hours, Visit Us (embed map or
   static map image), footer. Sticky "Book Appointment" button always
   visible during the intro and scroll.
3. Script `tools/make_rim.py` (or sharp/node script) to knock out the
   white center of rim_raw.png → rim_overlay.png with transparency.

## Phase 2 — Exam intro choreography (stills version)
Timeline driven by scroll position (scroll-jacked only during intro,
~3 viewport-heights, then normal scroll):
1. 0%: frame1 fullscreen (blurred page).
2. Scroll → crossfade frame1 → frame2 (descend placeholder).
3. Scroll → cut to frame3, then crossfade frame3 → frame4 (push-in placeholder).
4. Scroll → the CLICK: crossfade frame4 → frame5 (blur→sharp). Add a subtle
   scale snap (1.02→1.00) and optional muted "chk" tick.
5. Handoff: fade stills out revealing the live hero positioned to align
   with frame5's content; rim_overlay.png fixed on top as a porthole.
6. Continued scroll: normal page scroll under the rim. Rim scales up
   ~2.5x over the first 1.5 viewports so it becomes a soft corner frame,
   not a tight porthole, by the time Hours is on screen.

## Phase 3 — Video integration (after Phase 2 approved)
- Replace crossfades 1→2 and 3→4 with clip1/clip2 (scrub-on-scroll or
  play-through on first scroll; pick whichever feels better on mobile).
- Poster frames = the matching stills, so slow connections degrade to the
  Phase 2 experience seamlessly.
- Preload strategy: intro assets eager, below-fold lazy.

## Non-negotiables
- `prefers-reduced-motion`: skip intro entirely, land on clear hero.
- "Skip" affordance visible during intro; intro auto-skips on repeat
  visits (sessionStorage).
- Book Appointment reachable at every scroll position.
- Lighthouse: no layout shift after intro; total intro payload < 4 MB
  before video, videos compressed (H.264 + WebM, ~1 MB each target).
- All real text is live HTML (selectable, SEO-visible), never baked into
  images, except inside the intro stills.

## Acceptance
- On a phone: load → blurred page → scroll → machine → lens → click →
  clear hero → keep scrolling → Hours/Visit Us under a receding rim →
  tap Book Appointment → blinkvision.ca booking page.
- The frame5 → live-hero handoff is imperceptible.
