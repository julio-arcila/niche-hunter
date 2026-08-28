# Labelling criterion — topic domains, v4, 2026-08-28

**Self-contained. Read nothing else.** v1–v3 are superseded and must not be consulted.

## Why v4 exists — read this, it affects how you should treat the rule

v3 was written as a *diff* against v2 ("everything in v2 holds"), and its rater was
barred from reading v2. The rater was therefore applying a patch without its base, and
flagged rows that v2 had already settled. v3's 22.5% is an instrument error, not a
measurement of the rule. **v4 restates everything in one document** and adds the gaps
that were genuinely new.

Measured so far: v1 34.2% · v2 14.2% · v3 22.5% (void). **Bar: ≤10%.**

## The question

Is this video's *primary subject* the named domain, judged from the title and the
domain column alone?

**TRUE** when mainly about: the domain's concepts, theories, methods, results or
figures; an explanation, lecture, analysis, debate or critique within it; a specific
work, thinker, school or finding belonging to it; or its methods applied to a case
where the method is the point.

**FALSE** when the primary subject is something else — even if the domain is mentioned,
shares vocabulary, or the channel usually covers it. Including: generic motivation
borrowing the vocabulary; selling; tool and product content; passing mentions; reaction,
drama and entertainment formats.

**`?`** when the title is uninformative or unreadable. Never `0` for those — "we could
not tell" and "this is not about the domain" are different claims.

## Decisions, all of them

1. **Unknowable-from-title formats → FALSE unless the title names the substance.**
   "Live trading now" FALSE; "Live: walking through a Monte Carlo drawdown test" TRUE.
2. **Judge strictly against the row's own domain. Parent AND sibling disciplines are
   FALSE.** General philosophy is FALSE for `philosophy-of-science` unless the subject is
   science, evidence, method or theory-change. Descriptive geography and general history
   are FALSE for `geopolitics` unless the subject is power, states or strategy.
   Statistics is FALSE for `philosophy-of-science` unless the subject is inference or
   method as such. This covers the parent field, not only siblings.
3. **An explicit income claim, profit promise or sales call-to-action → FALSE**, even
   when real technique is also named. When edge calls collide, the selling clause wins.
4. **News: TRUE on significance, FALSE on occurrence.** "Why the strait closure reshapes
   Gulf shipping" TRUE; "Strait closed after incident" FALSE.
5. **A claimed paradigm shift inside another field → FALSE** for `philosophy-of-science`.
   TRUE only when the subject is the nature of paradigm change, evidence, or scientific
   revolution itself. See 12 for the applied case.
6. **Hashtags and channel branding are not subject matter.** Label the mechanism the
   title names; `#motivation` appended does not make it motivation, and a domain hashtag
   does not rescue a slogan.
7. **Cross-domain rows are judged against the domain column only.** A trading book
   sampled under `philosophy-of-science` is FALSE there. This applies in both directions:
   science-as-lens-on-philosophy is FALSE for `philosophy-of-science` unless the subject
   is scientific method itself.
8. **Bare topic labels, open questions and teases → FALSE.** A title is TRUE only if it
   names what is being explained **or** names both a subject and its stakes. No-verb
   topic labels ("US–Iran Stand-off"), open questions ("What happens next?") and reaction
   teases ("...and Putin won't like it") are FALSE. **But** a verbless noun phrase that
   names the analytical payload ("The Real Balance of Power") is TRUE, and a **specific**
   question naming its subject ("Is Trump's power fading?") is TRUE. The test is whether
   a reader knows what the video will argue about; withheld-subject teases ("a secret
   weapon that could change everything") stay FALSE.
9. **Tool and platform content → FALSE**, tutorials as well as reviews. A TradingView
   walkthrough, a bot setup, a software how-to: the subject is operating the tool. A
   video teaching the *skill* the tool serves stays TRUE. A **tool experiment or results
   video** ("I let an AI trade and made $102k") is FALSE — it is 3 and 9 together.
10. **Branded-product explainers → FALSE.** "<Brand> Formula, Explained" is product
    content whatever mechanism it recites. **Exception:** a critical evidence review of a
    named product ("does Ozempic extend lifespan — what the trials show") is TRUE; the
    subject is the evidence, not the product.
11. **Two boundaries.**
    a. **Biohacking vs general wellness:** TRUE requires a named biological mechanism,
       marker or measurement. General exercise, stretching, sleep hygiene or diet advice
       naming no mechanism is FALSE. An explainer with a named mechanism but **no
       intervention** ("why we age") is TRUE.
    b. **Philosophy of physics vs physics:** TRUE when the subject is interpretation,
       evidence, or what a theory *means*; FALSE when it explains the physics itself.
12. **Applied philosophy of science → TRUE.** "Using Kuhn's framework to understand how
    geography developed" is TRUE: the framework is the lens being examined. This is the
    "methods applied where the method is the point" clause, and it does not conflict with
    5 — 5 excludes *a phrase describing another field's events*, 12 admits *the lens
    being used and examined*.
13. **Signals, forecasts and daily calls → FALSE.** "Perfect entry today", daily
    predictions, price targets: ephemeral calls teach no method.
14. **Biography → TRUE when about the person's ideas, methods or contribution; FALSE
    when about their life, wealth or personality.** "How Jim Simons solved the market"
    is TRUE; "The billionaire who beat Wall Street" is FALSE.
15. **Comparison and ranking formats → FALSE unless the title names the analytical
    frame.** "Top 10 most powerful armies" FALSE; "Why force ratios mislead in the
    Taiwan strait" TRUE.
16. **Mixed titles:** if the domain is one topic among several with none dominant, FALSE.

## Controls

- Judge each row on its own. **Never reason about what proportion should be TRUE**, and
  never adjust a label to balance the set.
- Flag every row this rule still underdetermines, honestly and liberally.
- Label from the title as a viewer reads it in search results. Do not open videos, do not
  fetch URLs, do not consult any score.

**Falsification, pre-committed and unchanged:** if v4 leaves more than ~10% flagged, the
response is NOT a v5. It is to fit the axis on determined rows only and report the
excluded fraction as a stated limitation — a rule that cannot become decidable from a
title in four attempts is evidence about the task, not about the wording.
