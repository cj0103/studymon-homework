-- 业务表（打卡定额制 v2：按天定额 + 勾选凭据 + 家长扣减/驳回）
USE pokemon_homework;

CREATE TABLE IF NOT EXISTS sys_config (
    cfg_key VARCHAR(50) PRIMARY KEY,
    cfg_value VARCHAR(200) NOT NULL,
    memo VARCHAR(200)
) COMMENT='全局配置';

INSERT IGNORE INTO sys_config (cfg_key, cfg_value, memo) VALUES
('daily_base_exp', '230', '每日打卡定额经验'),
('daily_cap', '320', '每日经验自然上限，超出顺延次日'),
('study_weekdays', '0,1,2,3,4', '学习日=周一~周五(0=周一)'),
('fast_deadline', '21:30', '快手截止时间'),
('fast_multiplier', '1.2', '快手加成系数'),
('streak_bonus_days', '7', '连击奖所需连续天数'),
('streak_bonus_exp', '50', '连击奖经验'),
('penalty_options', '10,20', '扣减批准可选档'),
('exp_split_mode', 'even', 'even=队伍平分 / lead=主力60%后备各20%'),
('weekly_catch_times', '3', '每周野生捕获次数'),
('battle_weekday_open', '1', '测试期：学习日也开放道馆/捕捉 1=开 0=关(仅周末)'),
('team_max', '3', '出战队伍上限');

CREATE TABLE IF NOT EXISTS task_template (
    id INT PRIMARY KEY AUTO_INCREMENT,
    parent_id INT NOT NULL,
    task_name VARCHAR(50) NOT NULL,
    icon VARCHAR(20) DEFAULT 'book',
    category VARCHAR(10) DEFAULT 'study' COMMENT 'study|life',
    enabled TINYINT DEFAULT 1,
    sort INT DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(parent_id) REFERENCES parent_user(id)
) COMMENT='任务菜单（孩子勾选用，无逐项定额）';

CREATE TABLE IF NOT EXISTS checkin_record (
    id INT PRIMARY KEY AUTO_INCREMENT,
    student_id INT NOT NULL,
    task_date DATE NOT NULL,
    item_json TEXT NOT NULL COMMENT '孩子勾选 [{tid,name}]',
    adjusted_json TEXT COMMENT '家长补勾/调整，非空即标"家长调整"',
    status TINYINT DEFAULT 1 COMMENT '1待审 2已批 3扣批 4驳回',
    submit_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    approve_time DATETIME NULL,
    quick_win TINYINT DEFAULT 0 COMMENT '学习日21:30前提交',
    is_streak_day TINYINT DEFAULT 0 COMMENT '本日为第7连击日',
    base_exp INT DEFAULT 0, quick_exp INT DEFAULT 0,
    penalty INT DEFAULT 0, penalty_reason VARCHAR(100),
    reject_reason VARCHAR(100),
    streak_bonus INT DEFAULT 0,
    carry_from INT DEFAULT 0 COMMENT '前日顺延计入部分',
    carry_to INT DEFAULT 0 COMMENT '顺延至次日部分',
    exp_final INT DEFAULT 0 COMMENT '实发(含顺延扣减)',
    FOREIGN KEY(student_id) REFERENCES student_user(id),
    UNIQUE KEY uk_student_date(student_id, task_date)
) COMMENT='每日打卡（一天一条）';

CREATE TABLE IF NOT EXISTS student_carry (
    student_id INT PRIMARY KEY,
    carry_pending INT DEFAULT 0 COMMENT '待顺延发放经验',
    FOREIGN KEY(student_id) REFERENCES student_user(id)
) COMMENT='经验顺延状态';

CREATE TABLE IF NOT EXISTS exp_log (
    id INT PRIMARY KEY AUTO_INCREMENT,
    student_id INT NOT NULL,
    trainer_pokemon_id INT NOT NULL,
    exp_delta INT NOT NULL,
    reason VARCHAR(50) COMMENT 'checkin/penalty-reject/carry',
    ref_id INT,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(student_id) REFERENCES student_user(id)
) COMMENT='经验流水';

CREATE TABLE IF NOT EXISTS battle_record (
    id INT PRIMARY KEY AUTO_INCREMENT,
    student_id INT NOT NULL,
    kind VARCHAR(10) COMMENT 'wild/gym',
    ref_id INT COMMENT 'gym_id 或 pokedex_no',
    result VARCHAR(10) COMMENT 'win/lose/catch/flee',
    detail_json TEXT,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(student_id) REFERENCES student_user(id)
) COMMENT='战斗/捕获记录（战斗不产经验，胜利发徽章）';

ALTER TABLE student_user ADD COLUMN pin VARCHAR(10) NULL COMMENT '孩子4位数字PIN';
ALTER TABLE student_user ADD COLUMN exp_mode VARCHAR(10) NULL COMMENT '覆盖全局even/lead';
