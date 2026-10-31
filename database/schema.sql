-- GreenHands database schema (MySQL 8 / MariaDB 10.4+)
--
-- How to use in phpMyAdmin:
--   1. Create a database named `greenhands` with collation utf8mb4_unicode_ci.
--   2. Select it, open the "Import" tab, choose this file, click "Go".
-- Or run:  python scripts/init_db.py
--
-- utf8mb4_unicode_ci is named explicitly because MySQL 8 would otherwise default
-- to utf8mb4_0900_ai_ci, which MariaDB does not have.
-- Every table uses InnoDB (needed for foreign keys, transactions and row locks).

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS audit_logs;
DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS registrations;
DROP TABLE IF EXISTS activities;
DROP TABLE IF EXISTS locations;
DROP TABLE IF EXISTS volunteer_profiles;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS roles;

SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE roles (
  id   INT NOT NULL AUTO_INCREMENT,
  name VARCHAR(30) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_roles_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE users (
  id                    INT NOT NULL AUTO_INCREMENT,
  role_id               INT NOT NULL,
  username              VARCHAR(50)  NOT NULL,
  email                 VARCHAR(100) NOT NULL,
  password_hash         VARCHAR(255) NOT NULL,
  first_name            VARCHAR(50)  NOT NULL,
  last_name             VARCHAR(50)  NOT NULL,
  phone                 VARCHAR(20)  NULL,
  photo_path            VARCHAR(255) NULL,
  status                ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE',
  failed_login_attempts INT NOT NULL DEFAULT 0,
  locked_until          DATETIME NULL,
  created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_username (username),
  UNIQUE KEY uq_users_email (email),
  KEY ix_users_role_id (role_id),
  KEY ix_users_status (status),
  CONSTRAINT fk_users_role_id_roles FOREIGN KEY (role_id) REFERENCES roles (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE volunteer_profiles (
  id                      INT NOT NULL AUTO_INCREMENT,
  user_id                 INT NOT NULL,
  address                 VARCHAR(255) NULL,
  birth_date              DATE NULL,
  emergency_contact_name  VARCHAR(100) NULL,
  emergency_contact_phone VARCHAR(20)  NULL,
  created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_volunteer_profiles_user_id (user_id),
  CONSTRAINT fk_volunteer_profiles_user_id_users FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE locations (
  id            INT NOT NULL AUTO_INCREMENT,
  location_name VARCHAR(100) NOT NULL,
  address       VARCHAR(255) NOT NULL,
  details       TEXT NULL,
  PRIMARY KEY (id),
  KEY ix_locations_location_name (location_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE activities (
  id             INT NOT NULL AUTO_INCREMENT,
  created_by     INT NOT NULL,
  location_id    INT NOT NULL,
  title          VARCHAR(150) NOT NULL,
  description    TEXT NULL,
  activity_date  DATE NOT NULL,
  start_time     TIME NOT NULL,
  end_time       TIME NOT NULL,
  max_volunteers INT NOT NULL,
  requirements   TEXT NULL,
  status         ENUM('OPEN','CLOSED','CANCELLED','COMPLETED') NOT NULL DEFAULT 'OPEN',
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_activities_created_by (created_by),
  KEY ix_activities_location_id (location_id),
  KEY ix_activities_activity_date (activity_date),
  KEY ix_activities_status (status),
  KEY ix_activities_title (title),
  CONSTRAINT fk_activities_created_by_users FOREIGN KEY (created_by) REFERENCES users (id),
  CONSTRAINT fk_activities_location_id_locations FOREIGN KEY (location_id) REFERENCES locations (id),
  CONSTRAINT ck_activities_end_after_start CHECK (end_time > start_time),
  CONSTRAINT ck_activities_max_volunteers_positive CHECK (max_volunteers > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE registrations (
  id                INT NOT NULL AUTO_INCREMENT,
  activity_id       INT NOT NULL,
  user_id           INT NOT NULL,
  status            ENUM('PENDING','APPROVED','REJECTED','CANCELLED','COMPLETED') NOT NULL DEFAULT 'PENDING',
  registration_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at       DATETIME NULL,
  reviewed_by       INT NULL,
  remarks           TEXT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_registrations_activity_user (activity_id, user_id),
  KEY ix_registrations_user_id (user_id),
  KEY ix_registrations_status (status),
  KEY ix_registrations_reviewed_by (reviewed_by),
  CONSTRAINT fk_registrations_activity_id_activities FOREIGN KEY (activity_id) REFERENCES activities (id),
  CONSTRAINT fk_registrations_user_id_users FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT fk_registrations_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE notifications (
  id         INT NOT NULL AUTO_INCREMENT,
  user_id    INT NOT NULL,
  type       VARCHAR(30) NOT NULL,
  message    TEXT NOT NULL,
  is_read    BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_notifications_user_id_is_read (user_id, is_read),
  CONSTRAINT fk_notifications_user_id_users FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE audit_logs (
  id               INT NOT NULL AUTO_INCREMENT,
  user_id          INT NOT NULL,
  action           VARCHAR(50) NOT NULL,
  entity           VARCHAR(50) NOT NULL,
  record_reference INT NULL,
  timestamp        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  details          TEXT NULL,
  PRIMARY KEY (id),
  KEY ix_audit_logs_user_id (user_id),
  KEY ix_audit_logs_action (action),
  KEY ix_audit_logs_timestamp (timestamp),
  CONSTRAINT fk_audit_logs_user_id_users FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Reference data: the two roles always exist.
INSERT INTO roles (name) VALUES ('VOLUNTEER'), ('ADMIN');
