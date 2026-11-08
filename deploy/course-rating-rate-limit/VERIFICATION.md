# Course rating rate limit fix — 2026-11-08

- Deployed on top of existing production image `sha256:b1b728a0f49e44e926cb6b03a82c6a70daecd5d8435452404b0cc64930ab2248` to retain later server customizations.
- New image: `sha256:43232c39d44bb06c9b136cc91e88ee1375aa4f3e48228da4ec709d263720df9f`, built with `apply.py` and `Containerfile` from commit `642a51c8`.
- Image build and Python compilation passed. An isolated mocked check completed 1,200 internal calls without invoking the public rate-limited function.
- All six application services were recreated successfully; HTTPS ping passed on all three sites. A read-only rating calculation across all 969 courses on my-lk.mv-centr.ru completed without a rate-limit exception.
- The full setup wizard was not resubmitted; it creates or changes site data. The public endpoint retains its original rate limiter.
- Rollback: restore the protected runtime environment backup `.env.before-rate-limit-642a51c8` and recreate the six application services using the existing compose configuration. The previous image remains tagged `company-lms:rate-limit-base-20261108`.
