# ThreatRAG Stepping on a Weblog Design

# Target

Writing a technical blog for the author's own project rediscretion, with a focus on the three core issues revealed during the landing:

1. Declining recall rate after increased vector volume
2. Demolition of the Concordat scale
3. It is difficult to align the results directly with vector results

The aim of the article is not to be written in a curriculum or paper, but rather to settle a more stable GraphRG practice in the form of “real pedestals - > root cause - > engineering correction - > minor results”.

# Target reader #

- The main reader is the author's own project and the project's project interest Division
- Sub-readers are developers of RAG/ Graphrag
- Not oriented by interview presentations or product promotion

# Positioning articles

- Style: Technological Duplicate
- Structure: short background + extended by question group + end of summary methodology
- Depth: medium depth, allowing the introduction of key realization ideas such as Milvus Filter, submap control, reordering of summary
- Evidence: Supported by a small number of indicators or phenomena, not carried out as a whole experimental culture

# Core narrative

The article is organized around a main line:

> The system initially appears to have a complete chain of " vector recall + chart recall + reorder " , but as the scale of data and maps increases, recall quality and context control issues begin to be concentrated. The real focus of optimization is not to continue stacking models, but to limit the search space, the size of the context of the control map and the uniform expression of the isomer evidence.

# Recommended title

Priority title:

"Three pits I stepped on when I was doing Threatrag: Retrieving degradation, submersible explosion and transmutation."

Alternative title:

- A CTI Graphrag Project Reassembly: Why is the recall worse?
- From "recalling" to "recallability": three amendments I made in Theratrag

# Article structure

1. Opening Background

The page is contained in paragraphs 2 to 4, indicating the following:

- ThreatRAG for CTI scene, not pure vector RAG, but vector search, typographical recall, reordering, generating combination links
- The first version of the system works on small-scale data, but problems arise when the scale becomes larger
- This is not about the full system, but about the three most typical, impacting pits.

## 2. Pit One: When the vector changes, the recall rate drops

Fixed spread order:

- Initial intuition: more vectors, more stable recall.
- Practical phenomenon: when the data is up, the top-k is occupied by many similar but useless chunks
- Root analysis: too much space for retrieval, lack of metadata constraints, associated candidates flooded with noise
- Amendment: Milvus uses flyer before recall to narrow the candidate range and perform vector search
- Outcome expression: more stable recall results, higher density of relevant clips, declining recall

The conclusions highlighted in this section are:

> In the search of the knowledge base, limiting the search space first is often more effective than continuing embedding.

## 3. Pit II: Retrieving T-chart blast

Fixed spread order:

- Initial approach: multi-jumping neighbourhood expansion from the lifeline entity
- Physical phenomena: rapid expansion of nodes and edges, surge of token, many relationships that are adjacent but do not serve current problems
- Root analysis: Retrieving a natural combination explosion, local connection is not the same as reasoning.
- Amended scheme: limit the starting entity, control the hop, limit the margin and avoid sending the original large map directly downstream
- Result expression: the size of the context is down and the evidence remains critical

The conclusions highlighted in this section are:

> Graphrag is often not “failed” but “too much”.

4. Pit three: it's difficult to reorder the graph and vector results directly

Fixed spread order:

- Initial practice: throw text chunk with the map to reranker
- Practical issues: Text is a natural language section, with fragmentation structures at the edge of the map, with different particle sizes and expressions
- Root analysis: Isomer evidence is not semantically aligned first, and direct uniform scoring leads to unstable ranking
- Amended scheme: transform the sub-chart into a summary or relationship description block and reorder it with the text candidate
- Result expression: the result of the rearrangement is more stable and ultimately more like the “evidence collection” than the “structural debris build-up”

The conclusions highlighted in this section are:

> Do not let reranker face the nudity structure first by pressing it into comparable semantic units.

5. Closing Summary

At the end of the sentence, we do not make a grand leap, but we produce three principles of practice:

1. Reduce search space before searching
2. Recall pre-control scale before talking about coverage
3. Consistency of expression of isomeric evidence before uniform ranking

Finally, a wrap-up of the author's perspective:

> The surface of these pits, which appear to be occurring at the vector search, recall and reordering stages respectively, points essentially to the same thing: once the RAG system has reached its true scale, the question is no longer simply “can it be called back”, but “can it be contained within the limits available”.

# Writing tone

- In first person's name, emphasis on true trial error.
- Use more of the words "I thought at first and found out later..." This wrapping line
- Avoid dissertation and propaganda.
- Don't exaggerate the gains, don't say "an advanced approach"

# Forms of evidence

Only a few high-value results are retained:

- Changes in the density of relevant clips before and after vector recall
- Changes in the size of the subgraph or the length of the context
- Reorder cases where the quality of final evidence is more stable

No systematic trial forms are required, but at least one or two comparisons are sought to enhance credibility.

# It's a golden sentence

- When the scale of the data has grown, many times the recall of degradation has not been sufficiently robust, but the search space has not been clean.
- The most dangerous part of the structure is not too little information, but too easily out of control in local expansion.
- Reordering is not an all-embracing glue, and isomer evidence is not reliable in itself if it is not presented correctly.

# Non-target

- Incomplete presentation of all modules of ThreatRAG
- No complete dissertation experimental design.
- Not into deployment tutorials or API documents
- Without all the details of the project, only the idea of realization that is directly related to the three issues is retained
