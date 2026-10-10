-- 设备令牌：孩子平板 ?k= 免登录；家长手机专用链接（仍需 PIN 解锁）
CREATE TABLE IF NOT EXISTS device_token (
    token VARCHAR(48) PRIMARY KEY,
    role VARCHAR(10) NOT NULL COMMENT 'kid|parent',
    ref_id INT NOT NULL COMMENT 'role=kid时为student_id；role=parent时为parent_id',
    label VARCHAR(50) DEFAULT '' COMMENT '设备备注：学习平板/爸爸手机/妈妈手机',
    enabled TINYINT DEFAULT 1,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='设备令牌（浏览器无法读取MAC，等效设备绑定）';
