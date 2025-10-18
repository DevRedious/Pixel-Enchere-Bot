-- Script de création des tables MySQL pour VyroHost
-- À exécuter dans phpMyAdmin ou un client MySQL

-- Table des joueurs
CREATE TABLE IF NOT EXISTS players (
    discord_id BIGINT PRIMARY KEY,
    username VARCHAR(255) NOT NULL,
    ark_name VARCHAR(255),
    balance INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Table des transactions
CREATE TABLE IF NOT EXISTS transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    from_user_id BIGINT,
    to_user_id BIGINT NOT NULL,
    amount INT NOT NULL,
    transaction_type VARCHAR(50) NOT NULL,
    description TEXT,
    admin_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_from_user (from_user_id),
    INDEX idx_to_user (to_user_id),
    INDEX idx_created_at (created_at)
);

-- Table des enchères actives
CREATE TABLE IF NOT EXISTS active_auctions (
    thread_id BIGINT PRIMARY KEY,
    auction_data JSON NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table de l'historique des enchères
CREATE TABLE IF NOT EXISTS auction_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    dino_name VARCHAR(255) NOT NULL,
    final_price INT NOT NULL,
    won BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_created_at (created_at)
);

-- Table des tokens de rafraîchissement
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    discord_id BIGINT NOT NULL,
    token VARCHAR(255) NOT NULL UNIQUE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_discord_id (discord_id),
    INDEX idx_token (token),
    INDEX idx_expires_at (expires_at)
);

-- Insérer un utilisateur de test (optionnel)
INSERT IGNORE INTO players (discord_id, username, ark_name, balance) 
VALUES (123456789, 'TestUser', 'TestPlayer', 1000);

-- Afficher les tables créées
SHOW TABLES;