-- T5_001 rollback. Applying this loses event history; export/verify first.
DROP TABLE IF EXISTS entity_event_daily_metrics;
DROP TABLE IF EXISTS entity_events;
