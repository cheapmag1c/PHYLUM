# CORTEX

**PHYLUM 2.1 — CORTEX**  
*Brains are no longer a score. They can evolve.*

CORTEX gives resolved VIVARIUM organisms small, bounded neural controllers that make organism-level behavioral choices. It is deliberately not an LLM-per-animal system and it does not let a language model decide evolution.

## Canonical cognition

Each explicit organism can carry a tiny neural controller with:

- 10 normalized environmental/body inputs
- 3–8 active hidden neurons inside a fixed bounded representation
- 6 behavioral outputs: rest, forage, explore, avoid, socialize, mate
- inherited innate weights and biases
- inherited/mutable controller architecture
- lifetime reward-modulated plasticity
- an energetic processing cost
- NERVE-derived authority gating so primitive organisms remain mostly reflexive

CORTEX decisions feed back into VIVARIUM movement, foraging, resting, social contact, mating and predator avoidance. Survival and reproduction then determine which innate controllers leave descendants.

## Learning is not Lamarckian

A parent's learned plastic changes are **not** copied into offspring. Offspring recombine and mutate the parents' innate neural genomes, while their lifetime plastic layer starts blank. Evolution can therefore favor architectures that learn well without directly turning acquired memories into genes.

## Level of detail

Explicit organisms keep complete tiny controllers. Background cohorts keep only a compressed neural phenotype and deterministic controller seed. This preserves VIVARIUM's bounded-state design.

## Optional local LLM bridge

Canonical GitHub evolution never calls an LLM. This is intentional: PHYLUM history must stay deterministic, offline-capable and runnable in GitHub Actions.

For manual experiments only, CORTEX can probe any local OpenAI-compatible chat-completions endpoint:

```powershell
$env:PHYLUM_CORTEX_LLM_URL="http://127.0.0.1:1234/v1/chat/completions"
$env:PHYLUM_CORTEX_LLM_MODEL="your-local-model"
python -m phylum cortex --probe-llm
```

Without those environment variables, the bridge stays disabled. Normal `python -m phylum evolve` never invokes it even when configured.

## Inspecting CORTEX

```powershell
python -m phylum cortex
```

The report includes resolved controllers, compressed cohort controllers, mean hidden-neuron count, controller authority, plasticity, lifetime decisions and current action distribution.

## Evolutionary rule

CORTEX does not tell organisms to become intelligent. A more complex neural controller must pay its energetic cost and actually improve survival or reproduction to spread. Neural complexity can stagnate or regress if it is not useful.
