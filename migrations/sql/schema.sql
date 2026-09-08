-- InvoiceStock AI baseline schema. Apply through Alembic.

CREATE TABLE businesses (
	name VARCHAR(120) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	timezone VARCHAR(60) NOT NULL, 
	invoice_prefix VARCHAR(12) NOT NULL, 
	address VARCHAR(300) NOT NULL, 
	next_invoice INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE users (
	email VARCHAR(254) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	password_hash VARCHAR(300) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (email), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_users_business_id ON users (business_id);

CREATE TABLE products (
	sku VARCHAR(60) NOT NULL, 
	barcode VARCHAR(100) NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	category VARCHAR(80) NOT NULL, 
	unit VARCHAR(20) NOT NULL, 
	cost_price NUMERIC(14, 2) NOT NULL, 
	sell_price NUMERIC(14, 2) NOT NULL, 
	stock NUMERIC(14, 3) NOT NULL, 
	reorder_level NUMERIC(14, 3) NOT NULL, 
	active BOOLEAN NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (business_id, sku), 
	CHECK (stock >= 0), 
	CHECK (cost_price >= 0 AND sell_price >= 0), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_products_business_id ON products (business_id);

CREATE TABLE contacts (
	kind VARCHAR(20) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	phone VARCHAR(40) NOT NULL, 
	email VARCHAR(254) NOT NULL, 
	address VARCHAR(300) NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_contacts_business_id ON contacts (business_id);

CREATE TABLE expenses (
	category VARCHAR(80) NOT NULL, 
	amount NUMERIC(14, 2) NOT NULL, 
	date VARCHAR(10) NOT NULL, 
	note VARCHAR(500) NOT NULL, 
	document_reference VARCHAR(300) NOT NULL, 
	voided BOOLEAN NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_expenses_business_id ON expenses (business_id);

CREATE TABLE audit_logs (
	actor VARCHAR(36) NOT NULL, 
	action VARCHAR(80) NOT NULL, 
	entity_id VARCHAR(100) NOT NULL, 
	before JSON NOT NULL, 
	after JSON NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_audit_logs_business_id ON audit_logs (business_id);

CREATE TABLE agent_runs (
	agent_type VARCHAR(30) NOT NULL, 
	request_key VARCHAR(100) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	result JSON NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (business_id, request_key), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_agent_runs_business_id ON agent_runs (business_id);

CREATE TABLE action_keys (
	key VARCHAR(100) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (business_id, key), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_action_keys_business_id ON action_keys (business_id);

CREATE TABLE documents (
	kind VARCHAR(20) NOT NULL, 
	contact_id VARCHAR(36), 
	number VARCHAR(40), 
	request_key VARCHAR(100) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	subtotal NUMERIC(14, 2) NOT NULL, 
	discount NUMERIC(14, 2) NOT NULL, 
	tax NUMERIC(14, 2) NOT NULL, 
	total NUMERIC(14, 2) NOT NULL, 
	paid NUMERIC(14, 2) NOT NULL, 
	note VARCHAR(1000) NOT NULL, 
	finalized_at TIMESTAMP WITH TIME ZONE, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (business_id, number), 
	UNIQUE (business_id, request_key), 
	FOREIGN KEY(contact_id) REFERENCES contacts (id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_documents_business_id ON documents (business_id);

CREATE TABLE inventory_movements (
	product_id VARCHAR(36) NOT NULL, 
	qty NUMERIC(14, 3) NOT NULL, 
	reason VARCHAR(300) NOT NULL, 
	reference_id VARCHAR(100) NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_inventory_movements_product_id ON inventory_movements (product_id);

CREATE INDEX ix_inventory_movements_business_id ON inventory_movements (business_id);

CREATE TABLE document_items (
	document_id VARCHAR(36) NOT NULL, 
	product_id VARCHAR(36) NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	qty NUMERIC(14, 3) NOT NULL, 
	unit_price NUMERIC(14, 2) NOT NULL, 
	cost_snapshot NUMERIC(14, 2) NOT NULL, 
	line_total NUMERIC(14, 2) NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_document_items_document_id ON document_items (document_id);

CREATE INDEX ix_document_items_business_id ON document_items (business_id);
