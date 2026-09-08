-- SaaS extension baseline, migration 0002.

CREATE TABLE subscriptions (
	trial_ends_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	paid_until TIMESTAMP WITH TIME ZONE, 
	suspended BOOLEAN NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (business_id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_subscriptions_business_id ON subscriptions (business_id);

CREATE TABLE billing_orders (
	request_key VARCHAR(100) NOT NULL, 
	amount NUMERIC(14, 2) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	payment_id VARCHAR(100), 
	paid_at TIMESTAMP WITH TIME ZONE, 
	access_until TIMESTAMP WITH TIME ZONE, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (business_id, request_key), 
	UNIQUE (payment_id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_billing_orders_business_id ON billing_orders (business_id);

CREATE TABLE customer_payments (
	document_id VARCHAR(36) NOT NULL, 
	amount NUMERIC(14, 2) NOT NULL, 
	method VARCHAR(30) NOT NULL, 
	reference VARCHAR(100) NOT NULL, 
	actor VARCHAR(36) NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_customer_payments_business_id ON customer_payments (business_id);

CREATE INDEX ix_customer_payments_document_id ON customer_payments (document_id);

CREATE TABLE notifications (
	user_id VARCHAR(36) NOT NULL, 
	event_key VARCHAR(160) NOT NULL, 
	title VARCHAR(150) NOT NULL, 
	message VARCHAR(600) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	target VARCHAR(40) NOT NULL, 
	read_at TIMESTAMP WITH TIME ZONE, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (business_id, user_id, event_key), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_notifications_business_id ON notifications (business_id);

CREATE TABLE user_preferences (
	user_id VARCHAR(36) NOT NULL, 
	tour_completed BOOLEAN NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_user_preferences_business_id ON user_preferences (business_id);

CREATE TABLE feedback (
	user_id VARCHAR(36) NOT NULL, 
	category VARCHAR(30) NOT NULL, 
	rating INTEGER NOT NULL, 
	message VARCHAR(3000) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_feedback_business_id ON feedback (business_id);

CREATE TABLE backup_records (
	actor VARCHAR(36) NOT NULL, 
	kind VARCHAR(30) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_backup_records_business_id ON backup_records (business_id);
