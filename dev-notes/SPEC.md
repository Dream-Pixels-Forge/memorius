# Memorius Technical Specification: Neuroscience-Inspired Memory Architecture

## Overview
This specification outlines the technical architecture for enhancing Memorius with neuroscience-inspired memory mechanisms, hybrid retrieval systems, and improved observability to align with 2026 AI memory trends.

## Core Enhancements

### 1. Neuroscience-Inspired Consolidation Module

#### Biological Mechanisms Implemented
- **Sleep-Phase Consolidation**: 
  - Simulates offline memory strengthening during low-activity periods
  - Strengthens synapses based on retrieval frequency and novelty
  - Operates on configurable intervals or system idle detection
  
- **Interference-Based Forgetting**:
  - Reduces memory weights for similar, low-access memories
  - Prevents proactive and retroactive interference
  - Implements competitive learning between similar memory traces
  
- **Engram Maturation**:
  - Strengthens high-retrieval-count memories through repeated activation
  - Implements long-term potentiation (LTP) analogues
  - Converts fragile short-term traces to stable long-term storage
  
- **Neuromodulator-Gated Retrieval**:
  - Simulates acetylcholine (attention) and dopamine (novelty) modulation
  - Dynamically adjusts retrieval thresholds based on behavioral state
  - Enhances salient memories while suppressing distractors

#### Architecture
- **Consolidation Scheduler**: 
  - Background process triggering consolidation cycles
  - Configurable intervals or event-triggered (system idle, low load)
  - Graceful degradation under high load conditions
  
- **Weight Modification Engine**:
  - Applies biological rules to memory strength values
  - Maintains backward compatibility with existing storage
  - Operates on metadata level without altering core content
  
- **State Tracking**:
  - Tracks retrieval frequency, novelty scores, and contextual similarity
  - Uses lightweight in-memory structures to minimize overhead
  - Persists state periodically to survive restarts

### 2. Extended Knowledge Graph with Typed Temporal Edges

#### Edge Type Extensions
- **Temporal Edges**:
  - `temporal_before`: Memory A occurred before Memory B
  - `temporal_after`: Memory A occurred after Memory B
  - `temporal_overlapping`: Memories A and B have overlapping timeframes
  - `temporal_immediately_before`: Direct temporal precedence
  
- **Causal Edges**:
  - `causal_leads_to`: Memory A causally influences Memory B
  - `causal_prevented_by`: Memory A prevents occurrence of Memory B
  - `causal_contributes_to`: Memory A is a contributing factor to Memory B
  - `causal_triggered_by`: Memory B was triggered by Memory A
  
- **Episodic Edges**:
  - `episodic_part_of`: Memory is a component of a larger episodic event
  - `episodic_contains`: Memory contains sub-memories as components
  - `episodic_similar_to`: Memory shares contextual similarity with another
  - `episodic_preceded_by`: Memory occurred immediately before another in sequence
  
- **Semantic Edges**:
  - `semantic_instance_of`: Memory is an instance of a conceptual category
  - `semantic_similar_to`: Memory shares semantic meaning with another
  - `semantic_contradicts`: Memory semantically contradicts another (existing)
  - `semantic_specializes_in`: Memory represents a specialization of concept

#### Storage Implementation
- **Edge Table Extension**:
  - Add `relation_type` column with enum of all supported types
  - Maintain backward compatibility with existing `related`/`supersedes` values
  - Index on `(source_memory_id, relation_type, target_memory_id)` for fast lookups
  
- **Reasoning Engine**:
  - Graph traversal algorithms respecting edge type semantics
  - Temporal reasoning: detect inconsistencies in timelines
  - Causal reasoning: identify potential causal chains
  - Episodic reasoning: reconstruct event sequences
  - Semantic reasoning: conceptual categorization and inference

#### Query Integration
- **Graph Expansion Flags**:
  - `--expand_temporal`: Include temporally related memories
  - `--expand_causal`: Include causally related memories
  - `--expand_episodic`: Include episodically related memories
  - `--expand_semantic`: Include semantically related memories
  - `--expand_all`: Include all relation types (existing behavior)
  
- **Hybrid Scoring**:
  - Combine vector similarity with graph traversal scores
  - Weight factors configurable per relation type
  - Temporal proximity boosting for time-sensitive queries
  - Causal strength weighting for cause-effect queries

### 3. Hybrid Keyword/Vector Retrieval System

#### Architecture Layers
- **Vector Search Layer**:
  - Existing ChromaDB/SQLite-vec cosine similarity search
  - Sentence transformer embeddings (configurable provider)
  - Approximate nearest neighbor (ANN) search with HNSW/indexing
  
- **Keyword Search Layer**:
  - Inverted index using BM25/TF-IDF ranking
  - Term frequency-inverse document frequency scoring
  - Support for exact phrase matching and boolean operators
  - Language-agnostic tokenization with stopword filtering
  
- **Metadata Filter Layer**:
  - Existing folder/shelf/note/tag filtering via SQLite WHERE clauses
  - Temporal filtering based on timestamps and TTL
  - Custom metadata key-value filtering
  
- **Graph Activation Layer**:
  - Spreading activation from seed nodes through typed edges
  - Decay-based activation propagation
  - Context-sensitive node weighting
  
- **Score Fusion Layer**:
  - Learned or weighted combination of all signals
  - Configurable weighting per search context
  - Normalization to [0,1] range for consistent scoring
  - Re-ranking based on fused scores

#### Implementation Details
- **Inverted Index**:
  - SQLite-based FTS5 (Full-Text Search) extension for efficient keyword search
  - Tokenization pipeline: lowercasing, stopword removal, stemming
  - Positional tracking for phrase queries and proximity search
  - Automatic updates on memory store/delete operations
  
- **Score Normalization**:
  - Min-max normalization per signal type to [0,1] range
  - Learned weights via logistic regression or manual tuning
  - Context-aware weighting (e.g., higher keyword weight for code searches)
  
- **Fusion Strategies**:
  - Weighted sum: Σ(w_i × signal_i)
  - Learned ranking: Gradient boosted decision trees on features
  - Cascade ranking: Early termination on high-confidence matches
  - Hybrid approach: Vector pre-filter → keyword/graph re-rank

### 4. Token-Efficient Vector Index Options

#### Quantization Techniques
- **Product Quantization (PQ)**:
  - Split vectors into sub-vectors, quantize each with k-means centroids
  - Typical 4-8x storage reduction with <5% accuracy loss
  - Fast approximate distance computation via lookup tables
  
- **Binary Quantization (BQ)**:
  - Map vector components to +1/-1 based on sign
  - 32x storage reduction for float32→binary
  - Hamming distance approximation for angular similarity
  - Suitable for high-dimensional embeddings (768d+)
  
- **Scalar Quantization (SQ)**:
  - Uniform quantization of each dimension to b bits
  - Flexible storage/accuracy tradeoff (2-8 bits per dimension)
  - Balanced approach for mixed workloads

#### Implementation Architecture
- **Index Abstraction Layer**:
  - VectorStore ABC extended with quantization interface
  - Backend-specific implementations for ChromaDB/SQLite-vec
  - Transparent fallback to exact search when needed
  
- **Storage Format**:
  - Separate index files alongside main storage
  - Metadata tracking quantization parameters and training data
  - Incremental index updates for new/added vectors
  
- **Query Processing**:
  - Route to quantized index when enabled and appropriate
  - Fallback to exact search for high-precision requirements
  - Hybrid mode: quantized pre-filter → exact re-rank of top candidates
  
- **Training and Calibration**:
  - Periodic retraining on representative data samples
  - Calibration curves to map quantized distances to true similarities
  - Online learning options for adapting to data drift

### 5. Automatic Episodic vs. Semantic Segregation

#### Store Differentiation
- **Episodic Store**:
  - Append-optimized for time-series interaction traces
  - Optimized for sequential scans and temporal range queries
  - Higher write throughput, lower read complexity requirements
  - Shorter TTL defaults (hours to days)
  - Consolidation promotes important traces to semantic store
  
- **Semantic Store**:
  - Optimized for associative retrieval and similarity search
  - Vector indexing and graph relationships prioritized
  - Read-heavy workload with complex querying
  - Longer TTL defaults (weeks to years or permanent)
  - Receives promoted content from episodic store

#### Automatic Routing Mechanism
- **Input Classification**:
  - Raw interaction traces (from `mine`, hooks, transcripts) → Episodic
  - LLM-extracted facts (from `extract`, structured input) → Semantic
  - Manual user input → Configurable default (semantic)
  - System-generated insights → Semantic
  
- **Configuration Options**:
  - Per-shelf routing rules (episodic/semantic/both)
  - TTL policies per store type
  - Consolidation triggers and thresholds per store
  - Cross-store query routing and result merging

#### Cross-Store Operations
- **Unified Search API**:
  - Transparent search across both stores with appropriate routing
  - Result merging with source store attribution
  - Consistent ranking algorithm across stores
  
- **Promotion/Demotion Mechanisms**:
  - Based on retrieval frequency, novelty, and contextual importance
  - Configurable thresholds and evaluation windows
  - Background processes to avoid query latency impact
  
- **Consistency Guarantees**:
  - Eventual consistency between stores acceptable
  - Conflict resolution last-write-wins with timestamp resolution
  - Tombstone markers for deleted items during propagation

### 6. Production-Grade Observability

#### Metrics Infrastructure
- **Prometheus Endpoint**:
  - `/metrics` exposing OpenMetrics format
  - Protected by internal network or scrape token
  - Standard HTTP endpoint for scraping
  
- **Core Metrics**:
  - `memorius_recall_latency_seconds{type="vector|keyword|graph|hybrid"}`: Histogram
  - `memorius_consolidation_queue_size`: Gauge
  - `memorius_memory_utilization_score`: Gauge (0-1 scale)
  - `memorius_store_operations_total{counter="store|update|delete"}`: Counter
  - `memorius_search_operations_total{counter="vector|keyword|metadata|graph"}`: Counter
  - `memorius_graph_traversal_hops`: Histogram
  - `memorius_consolidation_events_total{counter="sleep|interference|maturation"}`: Counter
  - `memorius_cache_hit_ratio{gateway="vector|keyword|metadata"}`: Gauge
  
- **Resource Metrics**:
  - `memorius_storage_bytes{type="episodic|semantic|vector|metadata"}`: Gauge
  - `memorius_memory_count{type="active|archived|by_vault|by_shelf"}`: Gauge
  - `memorius_request_latency_seconds`: Histogram (REST/MCP)
  - `memorius_error_total{type="validation|auth|system|network"}`: Counter

#### Health Monitoring
- **Standard Endpoints**:
  - `/health/live`: Process liveness (basic check)
  - `/health/ready`: Dependency readiness (DB, queue, etc.)
  - `/health/startup`: Startup completion status
  
- **Dependency Checks**:
  - Database connectivity and response time
  - Vector store availability and search latency
  - External service availability (web providers, LLM backends)
  - Memory pressure and garbage collection indicators
  
- **Circuit Breakers**:
  - External service calls protected by circuit breakers
  - Automatic failover to cached responses or degraded mode
  - Manual reset after service recovery

#### Logging Enhancements
- **Structured JSON Logging**:
  - Single-line JSON per log entry
  - Standard fields: timestamp, level, message, service, environment, trace_id
  - Context fields: tenant_id, user_id, request_id, operation_type
  - No sensitive data in logs (PII, secrets, tokens)
  
- **Log Sampling**:
  - Adaptive sampling to control volume under high load
  - Retain 100% of error logs and security-relevant events
  - Configurable sampling rates for different log levels

### 7. Cross-Cutting Improvements

#### Backward Compatibility
- **Configuration**: All new features opt-in via configuration
- **APIs**: Existing interfaces unchanged; new features via additional parameters
- **Storage**: Schema migrations preserve all existing data
- **Behavior**: Default behavior maintains existing characteristics

#### Performance Considerations
- **Latency Budgets**:
  - Vector search: <100ms P95
  - Keyword search: <50ms P95
  - Graph traversal: <200ms P95 for 3-hop queries
  - Hybrid search: <300ms P95
  - Consolidation: <5s per cycle (configurable)
  
- **Throughput Targets**:
  - Store operations: 1000 ops/sec sustained
  - Search operations: 500 queries/sec sustained
  - Concurrent users: 100+ agents with reasonable latency
  
- **Resource Efficiency**:
  - Memory usage: <500MB baseline for typical usage
  - Disk usage: Quantization reduces storage footprint 4-8x
  - Network bandwidth: Minimal external dependencies required

#### Failure Modes and Degradation
- **Graceful Degradation**:
  - Vector search failure → fallback to keyword/metadata search
  - Keyword search failure → fallback to vector search
  - Graph search failure → fallback to vector-only search
  - Consolidation failure → continue with best-effort basic consolidation
  
- **Circuit Breaker Patterns**:
  - External service calls (web providers, LLM backends) protected
  - Automatic fallback to cached responses or local-only mode
  - Manual reset after service recovery
  
- **Storage Resilience**:
  - SQLite write-ahead logging for crash consistency
  - ChromaDB persistence with automatic recovery
  - Backup and restore procedures documented

## Interface Specifications

### Configuration Options
```yaml
neuroscience:
  consolidation:
    enabled: true
    interval_seconds: 3600  # 1 hour
    sleep_threshold_low_load: 0.3  # System load <30% triggers consolidation
    interference_strength: 0.1
    engram_threshold: 5.0  # Retrieval count for maturation
    neuromodulator_attention_weight: 0.4
    neuromodulator_novelty_weight: 0.3
  
knowledge_graph:
  typed_edges_enabled: true
  spreading_activation:
    enabled: true
    decay_factor: 0.7  # Per hop
    max_hops: 3
    activation_threshold: 0.1
  
hybrid_retrieval:
  enabled: true
  keyword_weight: 0.3
  vector_weight: 0.4
  metadata_weight: 0.2
  graph_weight: 0.1
  
token_efficient_index:
  enabled: false  # Opt-in for storage/accuracy tradeoff
  method: "pq"  # pq|bq|sq
  sub_vectors: 4
  bits_per_subvector: 8
  
store_segregation:
  enabled: true
  episodic_default_ttl_days: 7
  semantic_default_ttl_days: 365
  promotion_threshold_retrievals: 10
  demotion_threshold_days: 30
```

### API Extensions
#### Search Parameters
- `--expand_temporal`: Include temporally related memories
- `--expand_causal`: Include causally related memories  
- `--expand_episodic`: Include episodically related memories
- `--expand_semantic`: Include semantically related memories
- `--hybrid_search`: Enable keyword/vector/graph hybrid search
- `--token_efficient`: Use token-efficient index if available
- `--store_type episodic|semantic|both`: Specify target store(s)

#### Consolidation Parameters
- `--neuroscience`: Use neuroscience-inspired consolidation
- `-- consolidation_interval SECONDS`: Override default interval
- `--dry_run`: Preview changes without applying

#### Store-Specific Operations
- `memorius store --store episodic`: Force storage to episodic store
- `memorius store --store semantic`: Force storage to semantic store
- `memorius search --store episodic`: Search only episodic store
- `memorius search --store semantic`: Search only semantic store

## Implementation Roadmap

### Phase 1: Foundation (Weeks 1-2)
- [ ] Extended knowledge graph schema with typed edges
- [ ] Basic temporal/causal/episodic/semantic edge storage
- [ ] Graph querying with new edge types
- [ ] Unit tests for edge storage and retrieval

### Phase 2: Neuroscience Mechanisms (Weeks 2-4)
- [ ] Sleep-phase consolidation mechanism
- [ ] Interference-based forgetting implementation
- [ ] Engram maturation mechanism
- [ ] Neuromodulator-gated retrieval system
- [ ] Consolidation scheduler and background processing
- [ ] Unit tests for each biological mechanism

### Phase 3: Hybrid Retrieval System (Weeks 4-6)
- [ ] Inverted index (FTS5) implementation for keyword search
- [ ] Score fusion layer for combining search signals
- [ ] Hybrid search API integration
- [ ] Performance optimization and tuning
- [ ] Unit tests for keyword search and hybrid fusion

### Phase 4: Advanced Features (Weeks 6-8)
- [ ] Token-efficient vector index options (PQ/BQ/SQ)
- [ ] Automatic episodic/semantic segregation
- [ ] Cross-store query routing and promotion/demotion
- [ ] Production-grade observability (metrics, health checks, logging)
- [ ] Integration testing and performance validation
- [ ] Documentation and usage examples

### Phase 5: Validation and Optimization (Weeks 8-10)
- [ ] Performance benchmarking against baseline
- [ ] Accuracy validation for new retrieval mechanisms
- [ ] Load testing and stress testing
- [ ] Security review and penetration testing
- [ ] Documentation completion and examples
- [ ] Final QA and release preparation

## Dependencies and Requirements

### New Dependencies
- **sqlite3**: FTS5 extension (built-in to Python sqlite3)
- **scikit-learn**: For potential learned ranking models (optional)
- **numpy**: For numerical operations in quantization
- **prometheus-client**: For metrics endpoint

### Optional Dependencies (for enhanced features)
- **torch** or **tensorflow**: For learned ranking models (optional)
- **joblib**: For parallel processing in consolidation (optional)
- **lz4** or **zstd**: For compressed storage of index files (optional)

### Backward Compatibility Guarantees
- All existing APIs remain functional
- Configuration defaults preserve existing behavior
- Data migration scripts preserve all existing memories
- Performance characteristics maintained or improved for existing workloads
- No breaking changes to CLI or MCP interfaces