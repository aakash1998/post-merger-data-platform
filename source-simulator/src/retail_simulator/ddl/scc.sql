-- KAN-32: generated from source_ddl.py and approved schema.json.
CREATE DATABASE scc CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `scc`.`customer_master` (
    `customer_id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY NOT NULL,
    `customer_code` VARCHAR(20) COLLATE utf8mb4_bin NOT NULL,
    `customer_name` VARCHAR(160),
    `customer_type` VARCHAR(20),
    `email_address` VARCHAR(150),
    `phone_number` VARCHAR(40),
    `address_text` VARCHAR(300),
    `city` VARCHAR(80),
    `province` VARCHAR(40),
    `postal_code` VARCHAR(20),
    `country` VARCHAR(40),
    `customer_group` VARCHAR(30),
    `credit_limit` DECIMAL(12,2),
    `active_flag` VARCHAR(5),
    `created_at` DATETIME,
    `updated_at` DATETIME,
    `updated_by` VARCHAR(30)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX `customer_master_ix_0` ON `scc`.`customer_master` (customer_code);

CREATE INDEX `customer_master_ix_1` ON `scc`.`customer_master` (email_address);

CREATE INDEX `customer_master_ix_2` ON `scc`.`customer_master` (active_flag, customer_id);

DELIMITER $$
CREATE TRIGGER scc.`customer_master_immutable_pk` BEFORE UPDATE ON scc.`customer_master` FOR EACH ROW BEGIN IF NEW.`customer_id` <> OLD.`customer_id` THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Source primary key is immutable'; END IF; END$$
DELIMITER ;

CREATE TABLE `scc`.`item_master` (
    `item_id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY NOT NULL,
    `item_code` VARCHAR(30) COLLATE utf8mb4_bin NOT NULL,
    `item_description` VARCHAR(180),
    `department_code` VARCHAR(20),
    `department_name` VARCHAR(80),
    `brand_name` VARCHAR(60),
    `barcode` VARCHAR(40),
    `unit_code` VARCHAR(12),
    `units_per_pack` DECIMAL(10,3),
    `selling_price` DECIMAL(12,2),
    `last_cost` DECIMAL(12,2),
    `active_flag` VARCHAR(5),
    `created_at` DATETIME,
    `updated_at` DATETIME,
    `updated_by` VARCHAR(30)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX `item_master_ix_0` ON `scc`.`item_master` (item_code);

CREATE INDEX `item_master_ix_1` ON `scc`.`item_master` (barcode);

CREATE INDEX `item_master_ix_2` ON `scc`.`item_master` (department_code, active_flag);

DELIMITER $$
CREATE TRIGGER scc.`item_master_immutable_pk` BEFORE UPDATE ON scc.`item_master` FOR EACH ROW BEGIN IF NEW.`item_id` <> OLD.`item_id` THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Source primary key is immutable'; END IF; END$$
DELIMITER ;

CREATE TABLE `scc`.`locations` (
    `location_id` SMALLINT UNSIGNED AUTO_INCREMENT PRIMARY KEY NOT NULL,
    `location_code` VARCHAR(12) COLLATE utf8mb4_bin NOT NULL,
    `location_name` VARCHAR(100),
    `location_type` VARCHAR(20),
    `address_text` VARCHAR(250),
    `city` VARCHAR(80),
    `province` VARCHAR(40),
    `postal_code` VARCHAR(20),
    `country` VARCHAR(40),
    `timezone_name` VARCHAR(64),
    `active_flag` VARCHAR(5),
    `closed_on` DATE,
    `created_at` DATETIME,
    `updated_at` DATETIME,
    `updated_by` VARCHAR(30)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX `locations_ix_0` ON `scc`.`locations` (location_code);

CREATE INDEX `locations_ix_1` ON `scc`.`locations` (location_type, active_flag);

DELIMITER $$
CREATE TRIGGER scc.`locations_immutable_pk` BEFORE UPDATE ON scc.`locations` FOR EACH ROW BEGIN IF NEW.`location_id` <> OLD.`location_id` THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Source primary key is immutable'; END IF; END$$
DELIMITER ;

CREATE TABLE `scc`.`sales_orders` (
    `sales_order_id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY NOT NULL,
    `order_number` VARCHAR(30) NOT NULL,
    `business_date` DATE NOT NULL,
    `entered_at` DATETIME,
    `location_id` SMALLINT UNSIGNED,
    `till_code` VARCHAR(12),
    `customer_id_ref` INT UNSIGNED,
    `customer_code_ref` VARCHAR(20) COLLATE utf8mb4_bin,
    `customer_name_text` VARCHAR(160),
    `delivery_address_text` VARCHAR(300),
    `sales_channel` VARCHAR(20),
    `order_status` VARCHAR(20),
    `currency_text` VARCHAR(8),
    `subtotal_amount` DECIMAL(14,2),
    `discount_amount` DECIMAL(14,2),
    `tax_amount` DECIMAL(14,2),
    `freight_amount` DECIMAL(14,2),
    `total_amount` DECIMAL(14,2),
    `paid_amount` DECIMAL(14,2),
    `created_at` DATETIME,
    `updated_at` DATETIME,
    `updated_by` VARCHAR(30),
    FOREIGN KEY (`location_id`) REFERENCES `scc`.`locations` (`location_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX `sales_orders_ix_0` ON `scc`.`sales_orders` (location_id, business_date, order_number);

CREATE INDEX `sales_orders_ix_1` ON `scc`.`sales_orders` (business_date, sales_order_id);

CREATE INDEX `sales_orders_ix_2` ON `scc`.`sales_orders` (order_number);

CREATE INDEX `sales_orders_ix_3` ON `scc`.`sales_orders` (customer_id_ref);

CREATE INDEX `sales_orders_ix_4` ON `scc`.`sales_orders` (customer_code_ref);

CREATE INDEX `sales_orders_ix_5` ON `scc`.`sales_orders` (order_status, business_date);

DELIMITER $$
CREATE TRIGGER scc.`sales_orders_immutable_pk` BEFORE UPDATE ON scc.`sales_orders` FOR EACH ROW BEGIN IF NEW.`sales_order_id` <> OLD.`sales_order_id` THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Source primary key is immutable'; END IF; END$$
DELIMITER ;

CREATE TABLE `scc`.`sales_order_lines` (
    `sales_order_line_id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY NOT NULL,
    `sales_order_id` BIGINT UNSIGNED NOT NULL,
    `line_number` SMALLINT UNSIGNED NOT NULL,
    `item_id_ref` INT UNSIGNED,
    `item_code_ref` VARCHAR(30) COLLATE utf8mb4_bin,
    `description_text` VARCHAR(180),
    `unit_code` VARCHAR(12),
    `quantity` DECIMAL(12,3),
    `unit_price` DECIMAL(12,2),
    `discount_amount` DECIMAL(14,2),
    `tax_amount` DECIMAL(14,2),
    `line_amount` DECIMAL(14,2),
    `line_status` VARCHAR(12),
    `created_at` DATETIME,
    `updated_at` DATETIME,
    `updated_by` VARCHAR(30),
    UNIQUE (`sales_order_id`, `line_number`),
    FOREIGN KEY (`sales_order_id`) REFERENCES `scc`.`sales_orders` (`sales_order_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT `sales_order_lines_ck_0` CHECK (line_number > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX `sales_order_lines_ix_0` ON `scc`.`sales_order_lines` (item_id_ref);

CREATE INDEX `sales_order_lines_ix_1` ON `scc`.`sales_order_lines` (item_code_ref);

DELIMITER $$
CREATE TRIGGER scc.`sales_order_lines_immutable_pk` BEFORE UPDATE ON scc.`sales_order_lines` FOR EACH ROW BEGIN IF NEW.`sales_order_line_id` <> OLD.`sales_order_line_id` THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Source primary key is immutable'; END IF; END$$
DELIMITER ;

CREATE TABLE `scc`.`payment_transactions` (
    `payment_transaction_id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY NOT NULL,
    `sales_order_id` BIGINT UNSIGNED,
    `order_number_ref` VARCHAR(30),
    `location_id` SMALLINT UNSIGNED,
    `receipt_number` VARCHAR(30),
    `transaction_date` DATE NOT NULL,
    `transaction_time` DATETIME,
    `transaction_type` VARCHAR(15),
    `tender_code` VARCHAR(20),
    `amount` DECIMAL(14,2) NOT NULL,
    `currency_text` VARCHAR(8),
    `reference_text` VARCHAR(80),
    `posted_flag` VARCHAR(5),
    `reversal_of_id_ref` BIGINT UNSIGNED,
    `created_at` DATETIME,
    `updated_at` DATETIME,
    `updated_by` VARCHAR(30),
    FOREIGN KEY (`sales_order_id`) REFERENCES `scc`.`sales_orders` (`sales_order_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
    FOREIGN KEY (`location_id`) REFERENCES `scc`.`locations` (`location_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX `payment_transactions_ix_0` ON `scc`.`payment_transactions` (sales_order_id, transaction_date);

CREATE INDEX `payment_transactions_ix_1` ON `scc`.`payment_transactions` (location_id, transaction_date);

CREATE INDEX `payment_transactions_ix_2` ON `scc`.`payment_transactions` (receipt_number);

CREATE INDEX `payment_transactions_ix_3` ON `scc`.`payment_transactions` (order_number_ref);

CREATE INDEX `payment_transactions_ix_4` ON `scc`.`payment_transactions` (reference_text);

CREATE INDEX `payment_transactions_ix_5` ON `scc`.`payment_transactions` (reversal_of_id_ref);

DELIMITER $$
CREATE TRIGGER scc.`payment_transactions_immutable_pk` BEFORE UPDATE ON scc.`payment_transactions` FOR EACH ROW BEGIN IF NEW.`payment_transaction_id` <> OLD.`payment_transaction_id` THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Source primary key is immutable'; END IF; END$$
DELIMITER ;

CREATE TABLE `scc`.`stock_balance` (
    `stock_balance_id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY NOT NULL,
    `item_id` INT UNSIGNED NOT NULL,
    `location_id` SMALLINT UNSIGNED NOT NULL,
    `quantity_on_hand` DECIMAL(12,3),
    `quantity_on_order` DECIMAL(12,3),
    `quantity_allocated` DECIMAL(12,3),
    `unit_code` VARCHAR(12),
    `reorder_level` DECIMAL(12,3),
    `last_count_date` DATE,
    `balance_as_of` DATETIME,
    `created_at` DATETIME,
    `updated_at` DATETIME,
    `updated_by` VARCHAR(30),
    FOREIGN KEY (`item_id`) REFERENCES `scc`.`item_master` (`item_id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
    FOREIGN KEY (`location_id`) REFERENCES `scc`.`locations` (`location_id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX `stock_balance_ix_0` ON `scc`.`stock_balance` (item_id, location_id);

CREATE INDEX `stock_balance_ix_1` ON `scc`.`stock_balance` (location_id, item_id);

CREATE INDEX `stock_balance_ix_2` ON `scc`.`stock_balance` (balance_as_of);

DELIMITER $$
CREATE TRIGGER scc.`stock_balance_immutable_pk` BEFORE UPDATE ON scc.`stock_balance` FOR EACH ROW BEGIN IF NEW.`stock_balance_id` <> OLD.`stock_balance_id` THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Source primary key is immutable'; END IF; END$$
DELIMITER ;
