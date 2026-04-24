# Memco Domain Schemas

This document is the repo-local Phase 6 schema contract for private single-user memory. Psychometrics remains opt-in and non-factual until validated extraction is explicitly enabled.

## Biography

Supported categories:

- `identity`: `name`
- `age_birth`: `age`, `birth_date`, `birth_year`
- `residence`: `city`
- `origin`: `place`
- `education`: `institution`, `field`
- `family`: `relation`, `name`
- `pets`: `pet_type`, `pet_name`
- `health`: `health_fact`, `status`
- `languages`: `languages`
- `habits`: `habit`
- `goals`: `goal`
- `constraints`: `constraint`
- `values`: `value`, `context`
- `finances`: `financial_note`, `caution`
- `legal`: `legal_note`, `caution`
- `travel_history`: `location`, `event_at`, `date_range`
- `life_milestone`: `milestone`, `event_at`
- `communication_preference`: `preference`, `language`, `context`
- `other_stable_self_knowledge`: `fact`, `context`

## Experiences

`event` payloads support `event`, `summary`, `event_at`, `date_range`, `location`, `participants`, `valence`, `intensity`, `outcome`, `lesson`, `recurrence`, `linked_persons`, `linked_projects`, and `temporal_anchor`.

## Preferences

`preference` payloads support `value`, `preference_domain`, `preference_category`, `polarity`, `strength`, `is_current`, `valid_from`, `valid_to`, `original_phrasing`, `reason`, and `context`.

## Social Circle

Relationship payloads support `relation`, `target_label`, `target_person_id`, `is_current`, `closeness`, `trust`, `valence`, `aliases`, `is_private`, `sensitivity`, `relation_type`, and `related_person_name`. `relationship_event` uses the same optional relationship metadata plus `event` and `context`.

## Work

Supported categories:

- `employment`: `title`, `role`, `org`, `client`, `status`, `is_current`, `start_date`, `end_date`, `team`, `constraints`, `preferences`
- `engagement`: `engagement`, `role`, `org`, `client`, `status`, `start_date`, `end_date`, `outcomes`, `team`
- `role`: `role`, `is_current`, `status`, `start_date`, `end_date`
- `org`: `org`, `client`, `is_current`, `status`
- `project`: `project`, `role`, `org`, `outcomes`, `status`, `start_date`, `end_date`, `team`
- `skill`: `skill`
- `tool`: `tool`

## Psychometrics

Psychometrics is default-off. Candidate extraction may be enabled only explicitly and must remain non-diagnostic, evidence-bound, confidence-rated, and owner-visible only. Supported framework labels are kept as schema values, not diagnoses: Big Five, Schwartz Values, PANAS, VIA, cognitive ability profile, IRI empathy, Moral Foundations, Political Compass, and Kohlberg.
