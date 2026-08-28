# Labelling criterion — topic domains, v2, 2026-08-28

Written before the v2 labelling pass and before any v2 row was read. **v1 failed**: an
independent blind rater flagged **41 of 120 rows (34%)** as underdetermined by the rule,
spread evenly across all four domains (8–13 each), so the failure is the rule's, not the
rater's or one domain's. v1's labels are kept at
`reports/relevance_axis_fable_2026-08-28.jsonl` as the record of that pass and must not
be used to fit anything.

Everything in v1 still holds. This version only **decides the seven questions v1 left
open**, each stated so a rater can apply it from a title alone — which is the constraint
v1 kept violating by writing rules that needed the video.

**The question, unchanged:** is this video's *primary subject* the named domain?

**TRUE** when mainly about the domain's concepts, theories, methods, results or figures;
an explanation, lecture, analysis, debate or critique within it; a specific work,
thinker, school or finding belonging to it; or its methods applied to a case where the
method is the point.

**FALSE** when the primary subject is something else — generic motivation borrowing the
vocabulary, selling, tool-and-product reviews, passing mentions, reaction/drama formats.

## The seven decisions

1. **Livestreams and other unknowable-from-title formats → FALSE unless the title itself
   names the substance.** "Live trading now" is FALSE; "Live: walking through a Monte
   Carlo drawdown test" is TRUE. v1 made the test turn on whether reasoning was present,
   which a title cannot show. The label must be decidable from what is in front of you.

2. **Judge strictly against the row's own domain. Parent and sibling disciplines are
   FALSE.** General philosophy is FALSE for `philosophy-of-science` unless the subject is
   science, evidence, method or theory-change. Descriptive geography and general history
   are FALSE for `geopolitics` unless the subject is power, states or strategy.
   Statistics is FALSE for `philosophy-of-science` unless the subject is inference or
   method as such. A domain is not its parent field.

3. **An explicit income claim, profit promise or sales call-to-action makes the row
   FALSE, even when real technique is also named.** "My most profitable strategy
   revealed" is FALSE. The promise is what the video is for; the technique is the lure.
   When two edge calls collide, **the selling clause wins**.

4. **A single news event is TRUE when the title frames significance, FALSE when it
   reports occurrence.** "Why the strait closure reshapes Gulf shipping" is TRUE; "Strait
   closed after incident" is FALSE. v1 excluded news that "merely touches" the domain and
   said nothing about news that *is* the domain.

5. **A claimed paradigm shift inside another field is FALSE for `philosophy-of-science`.**
   Theory change within medicine is medicine. It is TRUE only when the subject is the
   nature of paradigm change, evidence or scientific revolution itself.

6. **Hashtags and channel branding are not subject matter.** If the title names a real
   mechanism, concept or method, label the mechanism — `#motivation` on the end does not
   make it motivation. Conversely a motivational slogan does not become substantive
   because a domain hashtag is appended.

7. **Cross-domain rows are judged against the domain column only.** A trading-methodology
   book sampled under `philosophy-of-science` is FALSE there. The question is never "does
   this belong to some domain in the corpus".

## Unchanged rules that still bind

- **Unreadable is `?`, never `0`.** "We could not read this" and "this is not about the
  domain" are different claims (data rule 7).
- Teaching a strategy is trading; mechanism is biohacking; structural analysis is
  geopolitics — subject to decision 3 above where a sales hook is present.
- Label from the title as a viewer would read it in search results. Do not open the
  video. Do not consult any score.
- **Judge each row on its own. Never reason about what proportion should be TRUE.**
- Flag any row the rule still underdetermines. If v2 leaves more than ~10% flagged, v2
  has failed too and gets a v3 rather than a fitted axis.
