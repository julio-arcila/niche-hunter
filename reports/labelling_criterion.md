# Labelling criterion — relevance sample, 2026-08-27

Written before any row was read, so the rule is not fitted to the data.

**The question:** is this video's *primary subject* the named niche?

**TRUE** when the video is mainly about:
- a specific event in the niche (a named crash, wreck, collapse, fraud, or case);
- a class of such events, or a comparison/list of them;
- the systems, investigations, causes, aftermath or regulation around them
  (accident investigation, structural forensics, securities enforcement, court
  procedure applied to real cases).

**FALSE** when the primary subject is something else, even if the niche is
mentioned in passing, shares vocabulary, or the channel usually covers it. In
particular:
- general news, politics or current affairs that merely touch the domain;
- adjacent-industry content with no failure/case at its centre (aircraft reviews,
  ship tours, company profiles, legal explainers with no case);
- product reviews, tutorials, vlogs, gaming, entertainment.

**Edge calls, fixed in advance:**
- Military combat losses count as aviation/maritime disasters only when the video
  is about the loss and its causes, not about the weapon or the war.
- A company's *business* story is corporate-collapse only if failure, fraud or
  insolvency is the subject — a growth story is not.
- Space and rail accidents are FALSE for aviation and maritime respectively;
  they are neither niche as seeded.
- Crime and homicide are FALSE for court-cases unless the video is about the
  trial, verdict, or legal proceedings rather than the crime.
- A non-English video is labelled on the same rule if its subject is legible from
  the title and description; otherwise it is skipped (`null`), not guessed.

**Labeller:** claude-opus-5, the same system that wrote the lexicon. That is a
real weakness and the reason for the independent spot-check; see the report.
