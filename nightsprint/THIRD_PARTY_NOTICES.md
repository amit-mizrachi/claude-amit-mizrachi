# Third-party notices

The `to-spec` and `to-tickets` skills in `skills/` are adapted from
[mattpocock/skills](https://github.com/mattpocock/skills) (`skills/engineering/to-spec` and
`skills/engineering/to-tickets`, upstream commit `d81f3a183412e71a5b1e84ca21bc1a35eea03a60`).

Changes from upstream:

- Removed `disable-model-invocation: true` and set `allow_implicit_invocation: true` in
  `agents/openai.yaml`, so agents can invoke both skills, not only a human.
- Added "Use when" triggers to both descriptions.
- Added a no-human path: when nobody can answer, the skill decides, records its assumptions and
  keeps going instead of waiting on a question.
- Added a local-markdown fallback (`.scratch/<feature-slug>/`) when no issue tracker is
  configured, in place of telling the user to run `/setup-matt-pocock-skills`.

The upstream license follows.

```
MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
