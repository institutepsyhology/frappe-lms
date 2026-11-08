# Section translation — 2026-11-08

- Built image `sha256:798c2cd4ada8b11d175569cefec91510f30810eb343192f6132cba02bb81bb48` on the prior production image `sha256:43232c39d44bb06c9b136cc91e88ee1375aa4f3e48228da4ec709d263720df9f` using commit `d4d748a9`.
- Compared the full gettext catalogs before and after: only `section` changed, to `раздел`.
- Recreated application services, cleared site caches, and verified HTTPS ping for all three sites. The live MV Centre translation API returned `section: раздел` and `lesson: урок`.
- The course overview source joins the two counts with ` · `; it does not contain the literal entity `&#x20;`. A visual browser check of the reported course was not performed.
- Rollback: restore protected runtime backup `.env.before-section-translation-d4d748a9`, recreate the six application services, and clear site caches. The prior image remains available as `company-lms:rate-limit-fix-642a51c8`.
