CREATE TABLE subscribers (
    "group" TEXT NOT NULL,
    id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    subscription_requests JSONB NOT NULL,
    last_seen TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY ("group", id),
    UNIQUE ("group", id)
);
