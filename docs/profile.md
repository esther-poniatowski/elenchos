---
tags:
  - specification
index: "[Elenchos documentation](docs/_index.md)"
aliases:
  - Findings profile
---
# Findings profile

This profile fixes the subset of SARIF 2.1.0 that a producer of findings writes and that Elenchos reads, and the identity that Elenchos builds for each finding. Each object of the profile cites the clause of the standard that defines it, so that a reader can check the object against the clause, and a producer can implement the profile without further choices. The grounds of each choice, and the options weighed, are recorded in the [decision on the findings profile](adr/findings-profile.md).

The profile has version 1, named by the key `elenchos/v1` of the identity.

## 1. Conformance

Two roles write a log:

- a **producer** is a checker of a domain tool, a direct SARIF producer in the sense of the standard. It writes one run per invocation, and imports no package of Elenchos;
- the **gate** is Elenchos. It runs the checks declared by the consumer ([gate configuration](configuration.md)), reads the logs of the producers, acts as a post-processor and as a result management system, and adds the identity and the suppressions of each result.

The status column of each table takes four values:

- *required*: the object is always written;
- *optional*: the object may be written, and the gate does not depend on it;
- *absent*: the object is never written in version 1;
- *gate only*: the gate writes the object, and a producer never does.

A producer conforms when its log satisfies sections 3 and 4, and when the test vectors of [section 6](#6-test-vectors) yield their expected identities from its output. The gate rejects a log that breaks a rule on which the identity or the verdict depends, as listed in [section 5.6](#56-rejected-input).

## 2. Sources and marks

- Standard text: *Static Analysis Results Interchange Format (SARIF) Version 2.1.0 Plus Errata 01*, OASIS Standard, 28 August 2023, file `sarif-v2.1.0-errata01-os-complete.pdf`, read as page images [oasis2023]. Page numbers are the printed page numbers of that file.
- Schema: `https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json` (draft-04, key `id`), read through a fetch tool that returns excerpts.

Each quotation carries one of three marks:

- **[p. N]**: quoted from the page image, verbatim;
- **[fetch]**: quoted from the HTML text through a summarizing fetch tool, with a quote limit of 125 characters. The wording is probably exact, but it was not compared with the page image;
- **[unverified]**: not found in the text read.

## 3. Log and run

| Object | Status | Content |
| --- | --- | --- |
| `sarifLog.version` | required | `"2.1.0"` |
| `sarifLog.$schema` | optional | the schema URI of errata 01 |
| `sarifLog.runs` | required | one run per invocation of a producer; the gate adds one run of its own, of driver `elenchos` |
| `run.tool.driver.name` | required | the tool name, matching `[a-z][a-z0-9-]*`; it is the first component of the identity |
| `run.tool.driver.version` or `semanticVersion` | required | the version of the producer |
| `run.tool.driver.rules` | required | one `reportingDescriptor` per rule that the tool can emit, whether or not the run emits it, with `id`, `shortDescription` and `defaultConfiguration.level` |
| `run.tool.driver.isComprehensive` | optional | `true`, since `rules` lists every rule |
| `run.invocations` | required for an incomplete run | exactly one `invocation` declaring the failure ([section 3, incomplete runs](#3-log-and-run)); optional for a complete run |
| `run.results` | required, except for a failed run whose analysis never began | every result detected by the run; absent, never `null`, when the analysis never began |
| `run.columnKind` | required when `results` is non-empty | `"unicodeCodePoints"` for a Python producer, `"utf16CodeUnits"` for a TypeScript producer |
| `run.originalUriBaseIds` | optional | `SRCROOT` mapped to the root of the consumer repository |
| `run.automationDetails` | optional | unused by version 1 |
| `run.tool` | never altered by the gate | see below |

**One run per producer.** A log merges several tools as several runs, never as one run.

- §3.1 [p. 27]: "SARIF defines an object model, the top level of which is the `sarifLog` object (§3.13), which contains the results of one or more analysis runs. The runs do not need to be produced by the same analysis tool."
- §1.2 [fetch]: a run is an "invocation of a specified analysis tool on a specified version of a specified set of analysis targets".
- §3.14.1 [fetch]: "A run object describes a single run of an analysis tool and contains the output of that run."
- §3.13.5, example [p. 48]: two tools analysing the same files are written as two `run` objects of one log.

**Tool object.** The gate adds fingerprints and suppressions to results, and leaves each `tool` object unchanged.

- §3.14.6 [p. 50]: "A `run` object **SHALL** contain a property named `tool` whose value is a `tool` object (§3.18) that describes the analysis tool that was run."
- §3.18.2 [fetch]: "A tool object SHALL contain a property named driver whose value is a toolComponent object".
- §3.19.8 [fetch]: "A toolComponent object SHALL contain a property named name"; §3.19.2 [fetch]: "At least one of version (§3.19.13) and semanticVersion (§3.19.12) SHOULD be present."
- §3.18.1 [fetch]: "the post-processing tool SHOULD NOT alter any part of the tool object."

**Rules of the driver.** The driver lists every rule that the tool can emit, including the rules that the run does not emit.

- §3.19.23 [fetch]: "A toolComponent object MAY contain a property named rules whose value is an array of zero or more unique" "reportingDescriptor objects (§3.49) each of which provides information about an analysis rule" "supported by the tool component."
- §3.19.30, NOTE [fetch]: "tools are permitted to emit rules (§3.19.23), notifications (§3.19.24), or taxa (§3.19.25) properties" "that contain only those items relevant to the current run."
- §3.19.30 [fetch]: "A toolComponent object SHOULD contain a property named isComprehensive whose value is a Boolean that is true if the" "component contains complete information for the content types specified by contents and false otherwise." "If isComprehensive is absent, it SHALL default to false."

The standard admits both a complete list and a list restricted to the run. The profile requires the complete list, for two reasons. First, the descriptors of a run then depend on the version of the tool alone, not on the findings of the run, as the discriminator does ([section 4.6](#46-partialfingerprints-and-fingerprints)). Second, a reader of the log learns which rules the tool evaluates, including those that found nothing. Each `ruleId` of a result names one descriptor of the list. The gate does not check the list, since neither the identity nor the verdict depends on it.

**Incomplete runs.** A run is *complete* when the producer evaluated every rule on every target. Otherwise, it is *incomplete*, in one of two forms:

- a *partial* run stops by design before the end of its analysis, for instance at the first failure of a producer whose stages each consume the output of the previous one;
- a *failed* run stops because the producer crashed, or could not begin its analysis.

The standard declares an incomplete analysis through the invocation of the run:

- §3.14.11 [fetch]: "A run object MAY contain a property named invocations whose value is an array of zero or more invocation objects".
- §3.20.14 [fetch]: "An invocation object SHALL contain a property named executionSuccessful whose value is a Boolean that is true if the" "engineering system that started the process knows that the analysis tool succeeded," "and false if the engineering system knows that the tool failed."
- §3.20.21 [fetch]: "Each element of the array represents a runtime condition detected by the invoked process". Further: "The presence within this array of any notification object whose level property" "is "error" SHALL mean that the run failed." Further: "A SARIF consumer SHALL NOT assume that a failed run contains a complete set of analysis results."
- §3.14.23 [fetch]: if the tool started "but failed to begin its analysis", `results` "MAY be present, and if present SHALL be null"; "In all other circumstances, results SHALL be present and SHALL contain all results detected by the tool."
- Schema, `run.results` [fetch]: of type `"array"`, it "must be present (but may be empty) if a log file represents an actual scan."
- Schema, `notification` [fetch]: `required` is `["message"]`; `level` takes `none`, `note`, `warning` or `error`, and defaults to `"warning"`.

The standard attaches the consequence sought, results that a consumer must not take as complete, to a *failed* run only (§3.20.21). No property of the standard declares a run that succeeded but stopped early: `isComprehensive` describes the metadata of a component, not its results. Therefore, a partial run declares itself failed, as a crashed run does. The profile states:

- an incomplete run holds `invocations` with exactly one invocation, whose `executionSuccessful` is `false`, and whose `toolExecutionNotifications` hold at least one notification of level `"error"` with a `message.text` stating why the analysis stopped;
- an incomplete run whose analysis began, partial or failed, holds in `results` every result detected before the stop, as §3.14.23 requires;
- a failed run whose analysis never began omits `results`. It never writes `null`, which the text admits but the schema excludes by typing `results` as an array;
- a complete run either omits `invocations`, or holds one invocation whose `executionSuccessful` is `true` and which holds no notification of level `"error"`.

A crashed producer reports itself in one of two ways. When it can still write its log, it writes a failed run, optionally with the `exception` of the notification, and exits with a status declared by the consumer. When it cannot, it writes no log or exits with an undeclared status, and the gate reports the check as failed ([section 3, run of the gate](#3-log-and-run)).

The gate reads a run as incomplete when one of its invocations holds `executionSuccessful` false, or a notification of level `"error"`, since either declares a failed run (§3.20.14, §3.20.21). The results of an incomplete run enter the merged log. The [gate configuration](configuration.md#4-stale-suppressions) states how the gate judges the run and its suppressions.

**Column kind.** Every producer reporting on text files writes `columnKind`.

- §3.14.27 [p. 57]: "If a SARIF producer processes text artifacts and `theRun.results` (§3.14.23) is non-empty, the `run` object **SHALL** contain a property named `columnKind`".

**Run of the gate.** The gate appends one run of driver `elenchos` to the merged log, after the runs of the producers. Its results have level `error`, an empty `suppressions` array, and one of five rules:

| `ruleId` | Resource and locus | Case |
| --- | --- | --- |
| `check/failed` | `path:<configuration>#/checks/<name>` | the earlier log of a check cannot be deleted, or its command cannot start or exits with an undeclared status |
| `check/missing-log` | `path:<configuration>#/checks/<name>` | the command ran to completion, but wrote no log |
| `check/invalid-log` | `path:<configuration>#/checks/<name>` | the log is not JSON, or breaks [section 5.6](#56-rejected-input) |
| `check/incomplete` | `path:<configuration>#/checks/<name>` | the log is valid, but holds an incomplete run ([section 3, incomplete runs](#3-log-and-run)) |
| `suppression/stale` | `path:<suppressions file>`, with the stale identity as discriminator | a suppression matches no result |

A producer never names its driver `elenchos`. The [gate configuration](configuration.md#3-runner) states when each result is written.

## 4. Result

| Object | Status | Content |
| --- | --- | --- |
| `ruleId` | required | the stable identifier of the rule within its tool: lowercase components matching `[a-z0-9][a-z0-9._-]*`, separated by `/` |
| `kind` | absent | defaults to `"fail"` |
| `level` | required | `"error"`, `"warning"` or `"note"` |
| `message.text` | required | the explanation; excluded from the identity |
| `locations` | required | exactly one `location` |
| `locations[0].logicalLocations` | required | exactly one `logicalLocation`, top-level, holding `name` and optionally `kind` |
| `logicalLocations[0].name` | required | `<resource>` or `<resource>#<locus>` ([section 4.5](#45-logical-location-resource-and-locus)) |
| `logicalLocations[0].kind` | optional | a JSON kind of §3.33.7 for a pointer locus, otherwise the locus type (`link`, `term`, …); excluded from the identity |
| `locations[0].physicalLocation` | required when the resource has a file or a folder | [section 4.4](#44-physical-location) |
| `partialFingerprints["discriminator/v1"]` | optional | written by the producer: the normalized offending content separating two findings at one locus, derived from the result alone ([section 4.6](#46-partialfingerprints-and-fingerprints)) |
| `fingerprints["elenchos/v1"]` | gate only | the identity of [section 5](#5-identity-string) |
| `suppressions` | gate only | never written by a producer; the gate adds it to every result of every run of the merged log ([section 4.7](#47-suppressions)) |
| `baselineState` | absent | [section 4.8](#48-baselinestate) |
| `properties` | optional | the payload of one tool, each name prefixed by the driver name |

### 4.1 `ruleId`

- §3.27.5 [p. 102]: "Depending on the circumstances, a `result` object either **SHALL**, **MAY**, or **SHALL NOT** contain a property named `ruleId` whose value is a hierarchical string (§3.5.4) whose leading components specify the stable identifier of the rule that was evaluated to produce the result. In addition to being stable, `ruleId` **SHOULD** be opaque."
- §3.27.5 [p. 102]: "A SARIF viewer or result management system **MAY** use the additional hierarchical components to allow a user to suppress a subset of the violations of a given rule."
- §3.27.5 [p. 103]: "Direct producers **SHALL** emit either or both of `ruleId` and `rule.id` (§3.27.7, §3.52.4)."
- §3.19.23 [fetch]: "the id properties (§3.49.3) of the reportingDescriptor objects do not need to be unique within the array."
- Schema, `result.ruleId`: "The stable, unique identifier of the rule, if any, to which this result is relevant."

The rule is looked up in `theTool` (§3.27.6, §3.27.7 [p. 103–104]), so a `ruleId` is scoped to its tool. No clause makes it unique across tools or across runs. Therefore, the identity holds the tool beside the `ruleId`. Two consequences follow:

- `/` inside a `ruleId` is meaningful: the leading components name the rule, and further components refine it;
- a rule moved from one tool to another changes its identity, so the gate reads a declared rename ([section 5.5](#55-renames)).

### 4.2 `level`

- §3.27.10 [p. 107]: "A `result` object **MAY** contain a property named `level` whose value is one of a fixed set of strings that specify the severity level of the result." The values are `"warning"`, `"error"`, `"note"`, `"none"` [p. 107–108].
- §3.27.10 [p. 108]: "If `kind` (§3.27.9) has any value other than `"fail"`, then if `level` is absent, it **SHALL** default to `"none"`". With `kind` equal to `"fail"`, an absent `level` is taken from the rule configuration, and otherwise "SET `level` to `"warning"`".
- §3.27.9 [p. 107]: "If `kind` is absent, it **SHALL** default to `"fail"`."

The default of an absent `level` depends on the rule configuration, so a producer always writes `level`. A producer level `info` has no SARIF value, and maps to `"note"`. The producer writes a default level; the gate decides the verdict from the configuration of the consumer, and does not rewrite `level`.

### 4.3 `message`

- §3.27.11 [p. 109]: "A `result` object **SHALL** contain a property named `message` whose value is a `message` object (§3.11) that describes the result."
- §3.11.2 [fetch]: "At least one of the text (§3.11.8) or id (§3.11.10) properties SHALL be present."

The profile requires `message.text`.

### 4.4 Physical location

- §3.27.12 [fetch]: "The locations array SHALL NOT be used to specify distinct occurrences of the same result".
- §3.28.3 [p. 119]: "If physical location information is available and the `logicalLocations` property (§3.28.4) is absent or empty, `physicalLocation` **SHALL** be present. If physical location is available and `logicalLocations` is present and non-empty, `physicalLocation` **MAY** be present."
- §3.29.2 [p. 121]: "Either the `artifactLocation` property (§3.29.3), the `address` property (§3.29.6), or both **SHALL** be present."
- §3.29.4 [p. 121]: "A `physicalLocation` object **MAY** contain a property named `region` […]. In particular, if the `physicalLocation` object occurs within the `locations` property (§3.27.12) of a `result` object (§3.27), the region property **SHALL** specify the region within the artifact where the result was detected." Same page: "If the `region` property is absent, the `physicalLocation` object refers to the entire artifact."
- §3.24.6 [fetch]: the role `"directory"` reads "The artifact is a directory (a container for other files and directories) rather than a file." By contrast, §1.2 [fetch] defines an artifact as a "sequence of bytes addressable via a URI".
- §3.4.4 [p. 29]: "If this `artifactLocation` object describes a top-level artifact and the value of its `uri` property (§3.4.3) is a relative reference, the `artifactLocation` object **SHOULD** contain a property named `uriBaseId`".

A physical location without a region denotes the whole artifact. The clause requiring a region binds when the result was detected in a part of the artifact. Therefore, a finding about a whole file or a whole folder omits the region. A folder is admitted through the artifact role `"directory"`, although the definition of §1.2 speaks of a sequence of bytes; that tension lies in the standard itself.

The profile writes the physical location as follows:

- `artifactLocation.uri` holds the repository-relative path, percent-encoded per RFC 3986;
- a folder URI ends with `/`. The standard imposes the final `/` only on `originalUriBaseIds` (§3.14.14 [fetch]), so this is a convention of the profile;
- `artifactLocation.uriBaseId` is `"SRCROOT"` on every relative URI;
- `region` is present for a finding in a part of a file, and absent for a whole file or a folder;
- `physicalLocation` is absent when the resource has no file, since the logical location suffices (§3.28.3).

**Field absent from the record.** A finding on a field that the record does not hold has no node of its own. Its region is the region of the closest existing ancestor node, and is absent when that ancestor is the whole document. Its locus stays the JSON Pointer of the missing field ([section 4.5](#45-logical-location-resource-and-locus)). The absence of a field is detected in its parent, so the region of the parent is the region "where the result was detected" (§3.29.4). The locus names the missing field, so that two missing fields of one parent keep distinct identities.

**File of a fetched source.** A finding on a file that exists only in a fetched dependency source is located where the consumer would materialize that file, relative to the root of the consumer. The URI of the artifact and the resource `path:` both name that path, even when the file is absent from the disk because the run stopped before materializing it. Therefore, the identity depends neither on a temporary staging path nor on the progress of the run. The path of materialization is fixed by the producer that materializes the sources.

### 4.5 Logical location: resource and locus

- §3.28.4 [p. 120]: "If logical location information is available and the `physicalLocation` property (§3.28.3) is absent, `logicalLocations` **SHALL** be present and non-empty." The NOTE: "`logicalLocations` is an array because some logical locations can be expressed in more than one way. For example, the logical location of an element in an HTML document might be expressed by an XML Path expression such as `/html/body/img[1]` or by a CSS selector such as `#logo`."
- §3.33.5 [p. 134]: "If this `logicalLocation` object represents a top-level logical location, then `fullyQualifiedName` **MAY** be present. If present, it **SHALL** equal `name`; if absent, it **SHALL** default to `name`. If this object does not represent a top-level logical location, `fullyQualifiedName` **SHOULD** be present."
- §3.33.8 [p. 139]: "If this `logicalLocation` object represents a nested logical location, then it **SHALL** contain a property named `parentIndex` whose value is the array index (§3.7.4) of the parent `logicalLocation` object within `theRun.logicalLocations` (§3.14.17)."
- §3.33.7 [p. 136–139]: kinds for JSON documents are `"object"`, `"array"`, `"property"`, `"value"`; "If none of those strings accurately describes the construct, kind **MAY** contain any value specified by the analysis tool."
- §3.28.1, NOTE [p. 119]: "The `logicalLocation.fullyQualifiedName` property (§3.33.5) is particularly convenient for fingerprinting."

The elements of `logicalLocations` are alternative expressions of *one* location, so a resource and its locus cannot occupy two elements. A result therefore holds exactly one top-level logical location, whose `name` joins the resource and the locus. A `fullyQualifiedName`, if written, equals `name`.

**Name.** The name is `<resource>` for the whole resource, and `<resource>#<locus>` otherwise. In the resource, `%` is written `%25` and `#` is written `%23`; the locus is written as is, since the name splits at its first `#`. A reader decodes exactly these two escapes, and rejects any other `%` sequence in the resource and a name ending with `#`. A general percent-decoder would accept names that no producer writes, and map two names onto one identity.

**Resource.** The resource takes one of two forms, each with a prefix, so that the two forms cannot collide:

- `id:<identifier>`, the record identifier declared by the schema (`x-identifier`), when one exists;
- `path:<path>`, the repository-relative POSIX path otherwise: no leading `/` or `./`, no empty, `.` or `..` segment, a folder ending with `/`, and the repository root written `./`.

**Locus.** The locus takes one of three forms:

- the empty locus, which denotes the whole resource. It is also the deterministic fallback when malformed content supplies no locus;
- a JSON Pointer (RFC 6901), opening on `/`, for a key path in structured data; each `~` is followed by `0` or `1`. A field path converts to a pointer as stated below. The pointer to the whole document, the empty string in RFC 6901, coincides with the empty locus;
- a typed locus `<type>:<value>`, with a type from a closed list: `link:<target as written>`, `task:<id>`, `slot:<name>`, `term:<glossary id>`, `symbol:<notation id>`.

**Field paths.** A field path, such as a field path of Ekphrasis, is a sequence of segments, each a key or an index. It converts to a JSON Pointer as follows:

- the empty sequence, the whole document, converts to the empty string;
- each segment contributes `/` followed by its token;
- the token of an index is its decimal form, without leading zero (RFC 6901, section 4);
- the token of a key is the key with each `~` replaced by `~0`, and then each `/` replaced by `~1` (RFC 6901, section 3). The order matters: the reverse order would turn `/` into `~01`.

For example, `relations[2].target` converts to `/relations/2/target`, the key `a/b` to `/a~1b`, the key `c~1d` to `/c~01d`, and the empty key to `/`. A key written in digits and an index of equal value yield one token; they cannot collide, since one parent is either a mapping or a sequence. A producer converts the segments, not the printed form of the path, since a printed form need not quote every key that holds `.`, `[` or `"`. This conversion moves to the addressing specification of Anagraphe once that specification is published; the profile will then cite it.

A new locus type takes a new version of the profile. The types `term` and `symbol` extend the list of the [decision on stable checker finding identities](https://github.com/esther-poniatowski/geonexus/blob/main/docs/_decisions/stable-checker-finding-identities.md), which admits key paths, task identifiers, link targets and generated slots.

### 4.6 `partialFingerprints` and `fingerprints`

- §3.27.16 [p. 111]: "Each property value in this object **SHALL** be a string that provides a stable identifier for the result. This identifier **SHALL**, to the extent that it is feasible, be the same for all results that are logically identical, and different for any two results that are logically distinct."
- §3.27.16 [p. 111]: "Each property name in this object **SHALL** be a versioned hierarchical string (§3.5.4.2)."
- §3.27.16 [p. 112]: "A direct SARIF producer **SHOULD NOT** populate this property. A SARIF converter **MAY** populate this property if the analysis tool's native output format provides a value that qualifies as a fingerprint (a stable identifier for the result). A result management system **MAY** populate this property when it ingests a SARIF file."
- §3.27.17 [p. 112–113]: "Each property value in this object **SHALL** be a string that contributes to the stable, unique identity, or 'fingerprint,' of the result" and "Each property name in this object **SHALL** be a versioned hierarchical string (§3.5.4.2)."
- §3.27.17 [p. 113]: "A result management system lacking that knowledge **SHOULD NOT** attempt to interpret the information embodied in the partial fingerprint names."
- §3.5.4.1 [fetch]: a hierarchical string is "a sequence of forward-slash-separated components"; "The grammar prohibits a component from containing a forward slash." §3.5.4.2 [fetch]: the last component has the form `version component = "v", non negative integer;`.
- Appendix B, normative [p. 197]: "A result management system **SHOULD** construct a fingerprint by using information contained in the SARIF file such as the name of the tool that produced the result. the rule id. the file system path to the analysis target."
- Appendix B [p. 197]: "An analysis tool **SHOULD NOT** include in `partialFingerprints` information that a result management system could deduce from other information in the SARIF file, for example, file hashes."
- Appendix B [p. 197]: "A result management system **SHOULD NOT** include an absolute line number (or an absolute byte location in a binary artifact) in its fingerprint computation."
- Schema: both objects are `"type": "object"` with `"additionalProperties": { "type": "string" }`; no pattern constrains the keys.

The profile draws four rules from these clauses:

- **Partial fingerprints.** A producer writes `partialFingerprints["discriminator/v1"]` only, and only when the discriminator is non-empty. The tool, the resource and the locus can be deduced from `run.tool.driver.name` and from the logical location, so Appendix B excludes them.
- **Discriminator.** A producer derives the discriminator from the result alone: its rule and its own offending content, such as a keyword, an identifier or a matched form. It never derives the discriminator from other results of the log: it does not write one only when two results share a locus, and does not number occurrences. Therefore, the identity of a finding stays stable when other findings appear or disappear, as §3.27.17 requires a partial fingerprint to contribute to a "stable, unique identity". The gate alone numbers identical occurrences ([section 5.3](#53-string-and-ordinal)).
- **Fingerprint.** The gate writes `fingerprints["elenchos/v1"]` on ingesting the logs, as a result management system may. A producer, a direct producer, does not.
- **Keys.** Every key of either object is a versioned hierarchical string. The schema does not check the key format, so the gate does. The profile also requires each component of a key to be non-empty, a restriction whose agreement with the grammar of §3.5.4 is **[unverified]**.

### 4.7 Suppressions

- §3.27.23 [p. 116]: "A `result` object **MAY** contain a property named `suppressions` whose value is an array of zero or more unique (§3.7.3) `suppression` objects (§3.35) each of which describes a request to 'suppress' a result".
- §3.27.23 [p. 116]: "If the array is non-empty, a consumer that needs to determine the result's suppression state **SHALL** examine the `status` properties (§3.35.3) of the `suppression` objects in the array."
- §3.27.23 [p. 116]: "The `suppressions` values for all `result` objects in `theRun` **SHALL** be either all `null` or all non-`null`."
- §3.35.2 [p. 142]: "A `suppression` object **SHALL** contain a property named `kind`"; values `"inSource"` ("suppressed by a syntactic construct offered by the programming language") and `"external"` ("The result is suppressed in an external, persistent store.").
- §3.35.3 [p. 142]: "A `suppression` object **MAY** contain a property named `status`"; values `"accepted"` ("The suppression is accepted."), `"underReview"`, `"rejected"`.
- §3.35.6 [fetch]: `justification` is "a user-supplied string that explains why the result was suppressed." Schema: `suppression.required` is `["kind"]`.
- §3.35.3 says nothing about an absent `status` [p. 142]: whether a suppression without `status` counts as accepted is **[unverified]**.

A baseline of the consumer lists tolerated findings, and may only shrink. Each entry is an accepted suppression held in an external store, the [suppressions file](configuration.md#2-suppressions-file) of the consumer. The profile therefore states:

- a producer writes no `suppressions` property, neither an array, even empty, nor `null`. The gate rejects a result that holds one ([section 5.6](#56-rejected-input));
- the gate adds `suppressions` to every result of every run of the merged log: the runs of the producers and its own run. The array is empty when the result is unsuppressed. That satisfies the all-or-none rule of §3.27.23 in every run;
- a baseline entry yields `{"kind": "external", "status": "accepted", "justification": "<reason>"}`;
- `status` is always written, since the meaning of its absence is not stated;
- `justification` is always written, since the decision on stable checker finding identities requires each baseline entry to state its reason;
- the date and the author of an entry, when given, go to the properties `elenchos/date` and `elenchos/author` of the suppression ([section 4.9](#49-properties));
- an entry matching no result is stale, and the gate reports it as a result of its own run ([section 3](#3-log-and-run)), so that the file only shrinks.

### 4.8 `baselineState`

- §3.27.24 [p. 116]: "A `result` object **MAY** contain a property named `baselineState` whose value is a string that specifies the state of this result with respect to some previous run, which we refer to as the 'baseline run.'" Values: `"new"`, `"unchanged"`, `"updated"`, `"absent"` ("This result was detected in the baseline run but was not detected in the current run.").
- §3.27.24 [p. 117]: "If `baselineState` is present on any `result` object in `theRun`, it **SHALL** be present on every such `result` object." NOTE 3: "The presence of `baselineState` on any `result` implies that the SARIF producer performed a comprehensive comparison between the results in the current run and those in some previous run."
- §3.14.5 [p. 50]: `baselineGuid` "**SHALL** equal the `automationDetails.guid` property (§3.14.3, §3.17.4) of some previous run", and "If `baselineGuid` is present, the `result.baselineState` property (§3.27.24) of every `result` object (§3.27) in `theRun` **SHALL** be computed with respect to the run specified by `baselineGuid`."

In SARIF, a baseline is a *previous run*, and `baselineState` compares the current run with it. A baseline of the consumer is a list of accepted debts, which [section 4.7](#47-suppressions) carries. `baselineState` is absent from version 1. A later version that writes it must write it on every result of a run, and emit each finding of the previous run that disappeared as a result of state `"absent"`.

### 4.9 `properties`

- §3.8.1 [fetch]: "every object defined in this document MAY contain a property named properties whose value is a property bag"; "The property names are hierarchical strings (3.5.4)"; "The components of the property names SHOULD be camelCase strings".

Each property name opens on the name of the driver (`hermeneia/layer`), so the payloads of two tools never collide after the merge.

## 5. Identity string

The identity of a result is the string `tool|ruleId|resource|locus|discriminator[|ordinal]`, written by the gate in `fingerprints["elenchos/v1"]`. It is readable in a baseline, and it splits back into its components.

### 5.1 Components

For each result of a run:

- `T` is `run.tool.driver.name`;
- `U` is `ruleId`;
- `R` and `L` are the resource and the locus read from `logicalLocations[0].name` ([section 4.5](#45-logical-location-resource-and-locus));
- `D` is `partialFingerprints["discriminator/v1"]`, or the empty string when the key is absent or its value is empty.

`T` and `U` follow the forms of sections 3 and 4.1, `R` one of the two resource forms, and `L` one of the three locus forms. `D` is free text.

### 5.2 Normalization and escaping

Each component is processed in two steps:

1. normalization to Unicode NFC;
2. escaping of `%` as `%25`, of `|` as `%7C`, and of each control character U+0000–U+001F and U+007F as `%XX`, in uppercase hexadecimal.

No case folding and no trimming apply: the producer emits normalized values. The forms of `T` and `U` exclude `%` and `|`, so the escaping changes only `R`, `L` and `D`.

The components are NFC before escaping, but the whole string is not guaranteed to be NFC: the escape `%7C` ends with `C`, which composes with a following combining mark (`%7C` followed by U+0327 normalizes to `%7Ç`). An identity string is therefore compared code point by code point, and never normalized again.

### 5.3 String and ordinal

The base string is `S₀ = T|U|R|L|D`, with trailing empty components removed. `R` is never empty, so `S₀` holds three to five components.

Results that share `S₀` across all runs of the log receive ordinals. `S₀` holds the tool, so only results of one tool can share it. Those results are sorted by four keys:

1. `region.startLine` of the physical location, 0 when absent;
2. `region.startColumn`, 0 when absent;
3. `message.text`;
4. the order of the input: runs in order, then results in order.

The first result keeps `S₀`. The *k*-th, *k* ≥ 2, receives `S₀` padded to five components, then `|k`. The ordinal reproduces the counts of the current baselines: a baseline counting *c* instances becomes the *c* identities `S₀`, `S₀|…|2`, …, `S₀|…|c`, and the instances beyond *c* in region order are new.

### 5.4 Parsing

An identity string parses back into its components by splitting at `|` and inverting the escapes. A string is accepted only if it is the canonical string of some identity, so that each identity has exactly one string. A parser rejects:

- fewer than three or more than six components;
- a trailing empty component, when the string holds three to five components;
- a sixth component that is not a decimal integer of at least 2 without leading zero;
- a `%` not followed by the uppercase hexadecimal code of an escaped character, and an unescaped control character;
- a component that is not NFC after unescaping;
- a component outside the forms of [section 5.1](#51-components).

### 5.5 Renames

The gate reads two declared maps from the configuration of the consumer, and applies them to stored suppressions:

- a map of rules, `old tool|old ruleId` to `new tool|new ruleId`, for a rule that moves between tools or is renamed;
- a map of resources, `path:<p>` to `id:<i>`, generated from the record registry of Anagraphe when a schema starts declaring `x-identifier`, or when a file moves.

### 5.6 Rejected input

The gate rejects a log that prevents the construction of an identity, or the verdict on a result. The rules of the identity are:

- a run without `tool.driver.name`;
- a result without `ruleId`;
- a `locations` array not holding exactly one object;
- a `logicalLocations` array not holding exactly one object with a `name`;
- a key of `fingerprints` or `partialFingerprints` that is not a versioned hierarchical string, or a value that is not a string;
- a component outside its form, or a name that breaks [section 4.5](#45-logical-location-resource-and-locus).

The rules of the verdict are:

- a log that is not an object of `version` `"2.1.0"` holding a non-empty array of runs;
- a run whose driver name does not match the form of section 3, or is `elenchos`;
- a run without an array of `results`, unless it declares an incomplete run ([section 3, incomplete runs](#3-log-and-run)). The gate cannot tell a partial run from a failed one, so it admits an absent `results` in either;
- an `invocations` that is not an array of objects each holding a boolean `executionSuccessful`, or a `toolExecutionNotifications` that is not an array of objects whose `level`, when present, is `"none"`, `"note"`, `"warning"` or `"error"`;
- a result whose `level` is absent or not one of `"error"`, `"warning"`, `"note"`, or that holds no `message.text`;
- a result holding `suppressions` or `fingerprints["elenchos/v1"]`, which the gate alone writes.

### 5.7 Excluded attributes

The identity excludes `message`, `level`, line and column, `kind`, and any suggested repair, as the decision on stable checker finding identities requires and Appendix B recommends. The message and the region only order identical occurrences ([section 5.3](#53-string-and-ordinal)).

## 6. Test vectors

The test vectors are published data files of the repository, read by its test suite and by every producer:

- [identity vectors](../specs/vectors/identity.json): each vector holds a SARIF log and the expected identity of each of its results, in the order of runs and results;
- [rejected vectors](../specs/vectors/rejected.json): each vector holds a log that the gate must reject.

Each vector states its case in `case` and `description`. Non-ASCII and decomposed characters are written as JSON escapes (`́`), so that a reader sees which code points a vector holds. The expected values were computed by a reference script independent of the implementation of Elenchos, except those of the cases `missing-field`, `partial-run` and `failed-run`, which were computed by hand.

## 7. Unverified and open points

Unverified clauses:

- §3.49.3, `reportingDescriptor.id`: only the schema description, "A stable, opaque identifier for the report", was read **[unverified]**;
- `reportingDescriptor.deprecatedIds`, which would carry a rename of a rule within one tool **[unverified]**;
- `invocation.ruleConfigurationOverrides` (§3.20.5), for recording the severities of the consumer **[unverified]**;
- §3.58, the `notification` object: only the schema was read, since the text read through the fetch tool ends before that clause **[unverified]**.

Open points:

- the resource of a finding in a composed project (a submodule): relative to the repository of the gate, or prefixed with the repository identifier of a logical target of Anagraphe;
- the locus of prose rules (Hermeneia, glossary occurrences): a locus type `section:` with a sentence as discriminator, against the term with an ordinal, which matches the current counts.

A crashed producer reports itself as a failed run when it can still write its log, and the gate reports a crash that leaves no valid log as a result of its own run ([section 3](#3-log-and-run)), as the [decision on the runner and the suppressions](adr/runner-and-suppressions.md) records.

---

## Sources

Marks follow the [legend of reading marks](../CONTRIBUTING.md#^reading-marks).

- [oasis2023] ◐ [OASIS, *Static Analysis Results Interchange Format (SARIF) Version 2.1.0 Plus Errata 01*, OASIS Standard, 28 August 2023](https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/sarif-v2.1.0-errata01-os-complete.pdf); the cited clauses were read, as page images or through a fetch tool, and each quotation carries its own mark; the standard was not read in full
