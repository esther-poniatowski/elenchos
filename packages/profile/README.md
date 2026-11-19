# @elenchos/profile

The package `@elenchos/profile` implements the findings profile of Elenchos in TypeScript, for a
tool that writes or reads findings logs. The package offers three operations:

- the check of a producer log against the profile;
- the reading of the resource and the locus from the name of a logical location;
- the resolution of a locus against its document, keyed entries included.

The specification is the [findings profile](../../docs/profile.md); the vectors of
[`specs/vectors/`](../../specs/vectors) fix the verdicts, and the tests of the package run them.
The modules import neither Node nor a host library, so the package runs in Obsidian on mobile.

## Installation

npm installs no subdirectory of a Git repository, so each release of Elenchos attaches the tarball
`elenchos-profile-<version>.tgz` of the package. A consumer names that tarball in its
`package.json`:

```json
"@elenchos/profile": "https://github.com/esther-poniatowski/elenchos/releases/download/v<version>/elenchos-profile-<version>.tgz"
```

## Interface

| Name | Returns |
| --- | --- |
| `violations(log)` | each `Violation` of a producer log: the JSON Pointer of the node and the rule broken; empty when the log conforms |
| `splitLocationName(name)` | the `Location` of a finding: its decoded resource and its locus; throws `ProfileError` for a name that no producer writes |
| `locationName(resource, locus)` | the name of a logical location |
| `resolveLocus(document, locus)` | the `Resolution` of a pointer locus: the positional path of the deepest node reached and the tokens left below it; `null` for a typed locus |
| `pointer(path)` | the JSON Pointer of a positional path |
| `PROFILE_SCHEMA_ID` | the absolute `$id` of the schema of a producer log |

The package leaves identities to the Python module `elenchos.profile`, since only consumers in
Python build them.
