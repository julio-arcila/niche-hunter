# Labelling criterion — topic domains, 2026-08-28

Written before any row was read, so the rule is not fitted to the data. Companion to
`labelling_criterion.md`, which governs the five disaster/true-crime niches and cannot
be reused here: it requires "a failure/case at its centre", and that requirement is
precisely what ADR-0033 found does not transfer. A topic domain has no event.

**The question, unchanged:** is this video's *primary subject* the named domain?

**TRUE** when the video is mainly about:
- the domain's concepts, theories, methods, results or figures;
- an explanation, lecture, analysis, debate or critique **within** the domain;
- a specific work, thinker, school or finding belonging to the domain;
- the domain's methods applied to a concrete case, where the method is the point.

**FALSE** when the primary subject is something else, even if the domain is mentioned
in passing, shares vocabulary, or the channel usually covers it. In particular:
- generic self-help or motivation borrowing the domain's vocabulary;
- selling — courses, signals, supplements, subscriptions — where the domain is the pitch;
- tool and product reviews where the tool, not the subject, is the point;
- news or partisan commentary that merely touches the domain;
- reaction, drama, listicle and entertainment formats.

**Edge calls, fixed in advance.** These are the ones this corpus will actually turn on:
- **Trading:** teaching a strategy, an indicator, or an analysis of a market IS on-niche.
  "I made $10k this week", signal-group promotion, and broker referrals are FALSE — the
  subject is the seller, not the method.
- **Biohacking:** mechanism, protocol and evidence discussion is TRUE. Supplement
  advertising and unexplained "do this every morning" listicles are FALSE.
- **Geopolitics:** structural or strategic analysis of states, alliances and resources is
  TRUE. Domestic partisan politics and election horse-race content are FALSE.
- **Philosophy of science:** explanation or critique of scientific method, evidence and
  theory is TRUE. "Science mindset" motivation and pop-science factoids are FALSE.
- A **practice** video is FALSE where the domain is the subject of study rather than the
  activity: a guided meditation is not esoterism-as-subject, a trading livestream with no
  reasoning is not trading-as-subject.
- **Language:** a video in any language may be TRUE. Unreadable-to-the-labeller is
  recorded as `?`, never as FALSE — "we could not read this" and "this is not about the
  domain" are different claims (data rule 7).

**Labels:** `1` = TRUE, `0` = FALSE, `?` = cannot tell / cannot read. Label the title as
a viewer would read it in search results. Do not open the video. Do not consult any
score — the sheet is deliberately blind, and the key is written separately.
