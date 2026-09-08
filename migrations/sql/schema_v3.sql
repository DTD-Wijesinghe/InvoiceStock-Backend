-- Security extension baseline, migration 0004.

CREATE TABLE auth_sessions (
	user_id VARCHAR(36) NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	UNIQUE (token_hash), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_auth_sessions_business_id ON auth_sessions (business_id);

CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id);

CREATE TABLE account_states (
	user_id VARCHAR(36) NOT NULL, 
	disabled BOOLEAN NOT NULL, 
	business_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
);

CREATE INDEX ix_account_states_business_id ON account_states (business_id);
