/*
 Navicat Premium Data Transfer

 Source Server         : localhost8
 Source Server Type    : MySQL
 Source Server Version : 80040 (8.0.40)
 Source Host           : localhost:3306
 Source Schema         : monitoring_standard

 Target Server Type    : MySQL
 Target Server Version : 80040 (8.0.40)
 File Encoding         : 65001

 Date: 22/06/2026 09:42:19
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for deform_crack_meter
-- ----------------------------
DROP TABLE IF EXISTS `deform_crack_meter`;
CREATE TABLE `deform_crack_meter`  (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `eid` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备唯一编号',
  `equip_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备名称/型号',
  `install_addr` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备安装地址（文字）',
  `lon` decimal(15, 6) NULL DEFAULT NULL COMMENT '经度',
  `lat` decimal(15, 6) NULL DEFAULT NULL COMMENT '纬度',
  `alt` decimal(15, 3) NULL DEFAULT NULL COMMENT '设备安装高程',
  `dt` bigint NULL DEFAULT NULL COMMENT '采集时间戳',
  `E` int NULL DEFAULT NULL COMMENT '设备剩余电量',
  `EV` decimal(10, 1) NULL DEFAULT NULL COMMENT '设备工作电压',
  `st` int NULL DEFAULT NULL COMMENT '采集数据状态',
  `cid` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '采集通道ID',
  `create_time` datetime NULL DEFAULT NULL COMMENT '数据入库时间',
  `sf_crack_width` decimal(15, 3) NULL DEFAULT NULL COMMENT '监测裂缝宽度',
  `sf_temp` decimal(10, 1) NULL DEFAULT NULL COMMENT '介质温度（测缝计内置测温）',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_deform_crack_meter_eid`(`eid` ASC) USING BTREE,
  INDEX `idx_deform_crack_meter_dt`(`dt` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 11 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of deform_crack_meter
-- ----------------------------
INSERT INTO `deform_crack_meter` VALUES (1, 'SF-equip001', '振弦式测缝计（VWP-SF-50mm）-001', '某某大坝坝体1#裂缝', 112.567773, 37.837910, 784.834, 1781913600, 38, 12.6, 1, 'SF-ch01', '2026-06-20 08:00:00', 2.772, 26.3);
INSERT INTO `deform_crack_meter` VALUES (2, 'SF-equip001', '振弦式测缝计（VWP-SF-50mm）-001', '某某大坝坝体1#裂缝', 112.567773, 37.837910, 784.834, 1782000000, 95, 11.8, 1, 'SF-ch01', '2026-06-21 08:00:00', 1.008, 15.8);
INSERT INTO `deform_crack_meter` VALUES (3, 'SF-equip002', '振弦式测缝计（VWP-SF-50mm）-002', '某某大坝坝体2#裂缝', 112.438114, 37.918284, 785.294, 1781913600, 56, 11.9, 0, 'SF-ch02', '2026-06-20 08:00:00', 2.123, 17.7);
INSERT INTO `deform_crack_meter` VALUES (4, 'SF-equip002', '振弦式测缝计（VWP-SF-50mm）-002', '某某大坝坝体2#裂缝', 112.438114, 37.918284, 785.294, 1782000000, 90, 12.0, 0, 'SF-ch02', '2026-06-21 08:00:00', 2.568, 15.9);
INSERT INTO `deform_crack_meter` VALUES (5, 'SF-equip003', '振弦式测缝计（VWP-SF-50mm）-003', '某某建筑物3#伸缩缝', 112.539410, 37.879202, 780.328, 1781913600, 81, 12.0, 0, 'SF-ch03', '2026-06-20 08:00:00', 1.458, 17.7);
INSERT INTO `deform_crack_meter` VALUES (6, 'SF-equip003', '振弦式测缝计（VWP-SF-50mm）-003', '某某建筑物3#伸缩缝', 112.539410, 37.879202, 780.328, 1782000000, 81, 12.5, 0, 'SF-ch03', '2026-06-21 08:00:00', 2.928, 20.2);
INSERT INTO `deform_crack_meter` VALUES (7, 'SF-equip004', '振弦式测缝计（VWP-SF-50mm）-004', '某某建筑物4#伸缩缝', 112.551410, 37.871229, 810.981, 1781913600, 84, 12.5, 0, 'SF-ch04', '2026-06-20 08:00:00', 1.305, 16.4);
INSERT INTO `deform_crack_meter` VALUES (8, 'SF-equip004', '振弦式测缝计（VWP-SF-50mm）-004', '某某建筑物4#伸缩缝', 112.551410, 37.871229, 810.981, 1782000000, 79, 12.6, 1, 'SF-ch04', '2026-06-21 08:00:00', 1.197, 20.3);
INSERT INTO `deform_crack_meter` VALUES (9, 'SF-equip005', '振弦式测缝计（VWP-SF-50mm）-005', '某某边坡5#裂缝', 112.599984, 37.834592, 791.701, 1781913600, 42, 11.7, 0, 'SF-ch05', '2026-06-20 08:00:00', 4.661, 25.9);
INSERT INTO `deform_crack_meter` VALUES (10, 'SF-equip005', '振弦式测缝计（VWP-SF-50mm）-005', '某某边坡5#裂缝', 112.599984, 37.834592, 791.701, 1782000000, 62, 11.7, 0, 'SF-ch05', '2026-06-21 08:00:00', 0.886, 24.2);

-- ----------------------------
-- Table structure for deform_gnss
-- ----------------------------
DROP TABLE IF EXISTS `deform_gnss`;
CREATE TABLE `deform_gnss`  (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `eid` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备唯一编号',
  `equip_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备名称/型号',
  `install_addr` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备安装/架设地址（文字）',
  `lon` decimal(15, 6) NULL DEFAULT NULL COMMENT '经度（设备架设点）',
  `lat` decimal(15, 6) NULL DEFAULT NULL COMMENT '纬度（设备架设点）',
  `alt` decimal(15, 3) NULL DEFAULT NULL COMMENT '设备架设高程',
  `dt` bigint NULL DEFAULT NULL COMMENT '采集时间戳',
  `E` int NULL DEFAULT NULL COMMENT '设备剩余电量',
  `EV` decimal(10, 1) NULL DEFAULT NULL COMMENT '设备工作电压',
  `st` int NULL DEFAULT NULL COMMENT '采集数据状态',
  `gnss_position_x` decimal(15, 3) NULL DEFAULT NULL COMMENT '平面坐标X（高斯投影）',
  `gnss_position_y` decimal(15, 3) NULL DEFAULT NULL COMMENT '平面坐标Y（高斯投影）',
  `gnss_position_h` decimal(15, 3) NULL DEFAULT NULL COMMENT '大地高',
  `gnss_horizontal_dis_n` decimal(15, 4) NULL DEFAULT NULL COMMENT '水平位移（北向）',
  `gnss_horizontal_dis_e` decimal(15, 4) NULL DEFAULT NULL COMMENT '水平位移（东向）',
  `gnss_vertical_dis` decimal(15, 4) NULL DEFAULT NULL COMMENT '垂直位移（沉降/隆起）',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_deform_gnss_eid`(`eid` ASC) USING BTREE,
  INDEX `idx_deform_gnss_dt`(`dt` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 11 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of deform_gnss
-- ----------------------------
INSERT INTO `deform_gnss` VALUES (1, 'GNSS-equip001', 'GNSS接收机（GN-03，静态精度±2.5mm+1ppm）-001', '某某路基监测点1（强制对中基座）', 112.427338, 37.941490, 784.842, 1781913600, 54, 11.7, 0, 4428055.435, 545439.312, 192.245, 0.0016, -0.0024, -0.0014);
INSERT INTO `deform_gnss` VALUES (2, 'GNSS-equip001', 'GNSS接收机（GN-03，静态精度±2.5mm+1ppm）-001', '某某路基监测点1（强制对中基座）', 112.427338, 37.941490, 784.842, 1782000000, 94, 11.7, 1, 4428422.092, 545037.547, 191.772, -0.0028, 0.0007, 0.0008);
INSERT INTO `deform_gnss` VALUES (3, 'GNSS-equip002', 'GNSS接收机（GN-03，静态精度±2.5mm+1ppm）-002', '某某路基监测点2（强制对中基座）', 112.570825, 37.824965, 799.199, 1781913600, 52, 12.4, 0, 4428132.406, 545600.879, 153.098, 0.0007, 0.0009, 0.0007);
INSERT INTO `deform_gnss` VALUES (4, 'GNSS-equip002', 'GNSS接收机（GN-03，静态精度±2.5mm+1ppm）-002', '某某路基监测点2（强制对中基座）', 112.570825, 37.824965, 799.199, 1782000000, 51, 12.1, 1, 4428131.925, 545673.073, 196.993, 0.0008, -0.0013, -0.0003);
INSERT INTO `deform_gnss` VALUES (5, 'GNSS-equip003', 'GNSS接收机（GN-03，静态精度±2.5mm+1ppm）-003', '某某坝顶监测点3（观测墩）', 112.517963, 37.979355, 800.188, 1781913600, 78, 12.1, 1, 4428450.664, 545594.155, 170.673, -0.0023, -0.0023, 0.0026);
INSERT INTO `deform_gnss` VALUES (6, 'GNSS-equip003', 'GNSS接收机（GN-03，静态精度±2.5mm+1ppm）-003', '某某坝顶监测点3（观测墩）', 112.517963, 37.979355, 800.188, 1782000000, 94, 11.6, 0, 4428823.272, 545765.397, 176.483, -0.0024, 0.0018, -0.0022);
INSERT INTO `deform_gnss` VALUES (7, 'GNSS-equip004', 'GNSS接收机（GN-03，静态精度±2.5mm+1ppm）-004', '某某路基监测点4（强制对中基座）', 112.529541, 37.856801, 794.694, 1781913600, 67, 12.0, 0, 4428199.323, 545723.911, 162.419, -0.0017, -0.0010, 0.0026);
INSERT INTO `deform_gnss` VALUES (8, 'GNSS-equip004', 'GNSS接收机（GN-03，静态精度±2.5mm+1ppm）-004', '某某路基监测点4（强制对中基座）', 112.529541, 37.856801, 794.694, 1782000000, 72, 11.6, 0, 4428678.246, 545950.073, 176.452, 0.0009, -0.0014, 0.0005);
INSERT INTO `deform_gnss` VALUES (9, 'GNSS-equip005', 'GNSS接收机（GN-03，静态精度±2.5mm+1ppm）-005', '某某路基监测点5（强制对中基座）', 112.467539, 37.913993, 784.250, 1781913600, 75, 12.6, 0, 4428213.101, 545152.422, 196.345, -0.0001, 0.0015, 0.0014);
INSERT INTO `deform_gnss` VALUES (10, 'GNSS-equip005', 'GNSS接收机（GN-03，静态精度±2.5mm+1ppm）-005', '某某路基监测点5（强制对中基座）', 112.467539, 37.913993, 784.250, 1782000000, 57, 11.8, 1, 4428324.776, 545064.864, 156.694, -0.0021, -0.0009, -0.0014);

-- ----------------------------
-- Table structure for deform_pore_pressure
-- ----------------------------
DROP TABLE IF EXISTS `deform_pore_pressure`;
CREATE TABLE `deform_pore_pressure`  (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `eid` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备唯一编号',
  `equip_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备名称/型号',
  `install_addr` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备安装地址（文字）',
  `lon` decimal(15, 6) NULL DEFAULT NULL COMMENT '经度',
  `lat` decimal(15, 6) NULL DEFAULT NULL COMMENT '纬度',
  `alt` decimal(15, 3) NULL DEFAULT NULL COMMENT '设备安装高程',
  `dt` bigint NULL DEFAULT NULL COMMENT '采集时间戳',
  `E` int NULL DEFAULT NULL COMMENT '设备剩余电量',
  `EV` decimal(10, 1) NULL DEFAULT NULL COMMENT '设备工作电压',
  `st` int NULL DEFAULT NULL COMMENT '采集数据状态',
  `pz_pressure` decimal(15, 4) NULL DEFAULT NULL COMMENT '监测渗压（孔隙水压力）',
  `pz_temp` decimal(10, 1) NULL DEFAULT NULL COMMENT '介质温度（渗压计内置测温）',
  `pz_depth` decimal(12, 2) NULL DEFAULT NULL COMMENT '设备埋置深度',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_deform_pore_pressure_eid`(`eid` ASC) USING BTREE,
  INDEX `idx_deform_pore_pressure_dt`(`dt` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 11 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of deform_pore_pressure
-- ----------------------------
INSERT INTO `deform_pore_pressure` VALUES (1, 'PZ-equip001', '振弦式渗压计（VWP-0.6MPa）-001', '某某水库大坝坝体1#监测孔', 112.479266, 37.980642, 817.926, 1781913600, 66, 11.9, 0, 0.4468, 16.4, 4.06);
INSERT INTO `deform_pore_pressure` VALUES (2, 'PZ-equip001', '振弦式渗压计（VWP-0.6MPa）-001', '某某水库大坝坝体1#监测孔', 112.479266, 37.980642, 817.926, 1782000000, 67, 12.2, 0, 0.4552, 23.7, 4.79);
INSERT INTO `deform_pore_pressure` VALUES (3, 'PZ-equip002', '振弦式渗压计（VWP-0.6MPa）-002', '某某水库大坝坝体2#监测孔', 112.525535, 37.880740, 797.709, 1781913600, 70, 12.5, 0, 0.3751, 21.2, 4.14);
INSERT INTO `deform_pore_pressure` VALUES (4, 'PZ-equip002', '振弦式渗压计（VWP-0.6MPa）-002', '某某水库大坝坝体2#监测孔', 112.525535, 37.880740, 797.709, 1782000000, 31, 11.8, 0, 0.1751, 22.0, 6.10);
INSERT INTO `deform_pore_pressure` VALUES (5, 'PZ-equip003', '振弦式渗压计（VWP-0.6MPa）-003', '某某水库大坝坝体3#监测孔', 112.431953, 37.931035, 788.407, 1781913600, 41, 12.7, 0, 0.3805, 24.1, 4.32);
INSERT INTO `deform_pore_pressure` VALUES (6, 'PZ-equip003', '振弦式渗压计（VWP-0.6MPa）-003', '某某水库大坝坝体3#监测孔', 112.431953, 37.931035, 788.407, 1782000000, 40, 12.2, 1, 0.1084, 15.0, 6.21);
INSERT INTO `deform_pore_pressure` VALUES (7, 'PZ-equip004', '振弦式渗压计（VWP-0.6MPa）-004', '某某边坡4#渗压孔', 112.580900, 37.825412, 807.788, 1781913600, 39, 11.6, 1, 0.1994, 20.6, 5.98);
INSERT INTO `deform_pore_pressure` VALUES (8, 'PZ-equip004', '振弦式渗压计（VWP-0.6MPa）-004', '某某边坡4#渗压孔', 112.580900, 37.825412, 807.788, 1782000000, 71, 12.3, 0, 0.4250, 17.2, 6.90);
INSERT INTO `deform_pore_pressure` VALUES (9, 'PZ-equip005', '振弦式渗压计（VWP-0.6MPa）-005', '某某水库大坝坝体5#监测孔', 112.572758, 37.973687, 802.604, 1781913600, 36, 12.7, 0, 0.4226, 19.0, 4.90);
INSERT INTO `deform_pore_pressure` VALUES (10, 'PZ-equip005', '振弦式渗压计（VWP-0.6MPa）-005', '某某水库大坝坝体5#监测孔', 112.572758, 37.973687, 802.604, 1782000000, 71, 12.6, 0, 0.4064, 19.9, 7.08);

-- ----------------------------
-- Table structure for deform_soil_pressure
-- ----------------------------
DROP TABLE IF EXISTS `deform_soil_pressure`;
CREATE TABLE `deform_soil_pressure`  (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `eid` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备唯一编号',
  `equip_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备名称/型号',
  `install_addr` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备安装地址（文字）',
  `lon` decimal(15, 6) NULL DEFAULT NULL COMMENT '经度',
  `lat` decimal(15, 6) NULL DEFAULT NULL COMMENT '纬度',
  `alt` decimal(15, 3) NULL DEFAULT NULL COMMENT '设备安装高程',
  `dt` bigint NULL DEFAULT NULL COMMENT '采集时间戳',
  `E` int NULL DEFAULT NULL COMMENT '设备剩余电量',
  `EV` decimal(10, 1) NULL DEFAULT NULL COMMENT '设备工作电压',
  `st` int NULL DEFAULT NULL COMMENT '采集数据状态',
  `sp_pressure` decimal(15, 4) NULL DEFAULT NULL COMMENT '监测土压力',
  `sp_freq` decimal(10, 1) NULL DEFAULT NULL COMMENT '振弦工作频率',
  `sp_temp` decimal(10, 1) NULL DEFAULT NULL COMMENT '介质温度（土压力计内置测温）',
  `sp_depth` decimal(12, 2) NULL DEFAULT NULL COMMENT '设备埋置深度',
  `sp_calib_time` datetime NULL DEFAULT NULL COMMENT '上次校准时间',
  `sp_direction` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '压力测量方向',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_deform_soil_pressure_eid`(`eid` ASC) USING BTREE,
  INDEX `idx_deform_soil_pressure_dt`(`dt` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 11 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of deform_soil_pressure
-- ----------------------------
INSERT INTO `deform_soil_pressure` VALUES (1, 'SP-equip001', '振弦式土压力计（VWP-SP-1.0MPa）-001', '某某路基1#基底压力点', 112.522583, 37.931131, 788.598, 1781913600, 41, 12.3, 0, 0.5391, 1512.5, 22.3, 4.66, '2025-01-15 09:30:00', '垂直');
INSERT INTO `deform_soil_pressure` VALUES (2, 'SP-equip001', '振弦式土压力计（VWP-SP-1.0MPa）-001', '某某路基1#基底压力点', 112.522583, 37.931131, 788.598, 1782000000, 78, 12.4, 0, 0.4216, 1667.5, 15.3, 3.98, '2025-01-15 09:30:00', '坡向');
INSERT INTO `deform_soil_pressure` VALUES (3, 'SP-equip002', '振弦式土压力计（VWP-SP-1.0MPa）-002', '某某边坡支护结构2#监测点', 112.407374, 37.876270, 805.037, 1781913600, 48, 11.5, 0, 0.2306, 1609.0, 18.8, 5.09, '2025-01-15 09:30:00', '反向坡向');
INSERT INTO `deform_soil_pressure` VALUES (4, 'SP-equip002', '振弦式土压力计（VWP-SP-1.0MPa）-002', '某某边坡支护结构2#监测点', 112.407374, 37.876270, 805.037, 1782000000, 56, 12.4, 1, 0.2061, 1698.6, 17.5, 4.45, '2025-01-15 09:30:00', '垂直');
INSERT INTO `deform_soil_pressure` VALUES (5, 'SP-equip003', '振弦式土压力计（VWP-SP-1.0MPa）-003', '某某挡土墙3#土压力点', 112.480053, 37.839790, 781.657, 1781913600, 72, 12.4, 0, 0.1410, 1529.8, 23.9, 3.98, '2025-01-15 09:30:00', '水平');
INSERT INTO `deform_soil_pressure` VALUES (6, 'SP-equip003', '振弦式土压力计（VWP-SP-1.0MPa）-003', '某某挡土墙3#土压力点', 112.480053, 37.839790, 781.657, 1782000000, 84, 12.0, 0, 0.4211, 1625.5, 19.8, 5.80, '2025-01-15 09:30:00', '水平');
INSERT INTO `deform_soil_pressure` VALUES (7, 'SP-equip004', '振弦式土压力计（VWP-SP-1.0MPa）-004', '某某边坡支护结构4#监测点', 112.462494, 37.948602, 812.743, 1781913600, 92, 11.9, 0, 0.4388, 1558.7, 21.2, 5.80, '2025-01-15 09:30:00', '坡向');
INSERT INTO `deform_soil_pressure` VALUES (8, 'SP-equip004', '振弦式土压力计（VWP-SP-1.0MPa）-004', '某某边坡支护结构4#监测点', 112.462494, 37.948602, 812.743, 1782000000, 78, 12.7, 0, 0.5418, 1533.1, 20.9, 4.97, '2025-01-15 09:30:00', '坡向');
INSERT INTO `deform_soil_pressure` VALUES (9, 'SP-equip005', '振弦式土压力计（VWP-SP-1.0MPa）-005', '某某路基5#基底压力点', 112.528360, 37.992194, 810.643, 1781913600, 64, 12.1, 0, 0.4352, 1659.9, 23.7, 4.77, '2025-01-15 09:30:00', '垂直');
INSERT INTO `deform_soil_pressure` VALUES (10, 'SP-equip005', '振弦式土压力计（VWP-SP-1.0MPa）-005', '某某路基5#基底压力点', 112.528360, 37.992194, 810.643, 1782000000, 60, 12.4, 0, 0.4943, 1525.0, 20.1, 5.65, '2025-01-15 09:30:00', '垂直');

-- ----------------------------
-- Table structure for deform_total_station
-- ----------------------------
DROP TABLE IF EXISTS `deform_total_station`;
CREATE TABLE `deform_total_station`  (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `eid` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备唯一编号',
  `equip_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备名称/型号',
  `install_addr` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备/测站安装地址',
  `stn_id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '测站点编号',
  `dt` bigint NULL DEFAULT NULL COMMENT '采集时间戳',
  `E` int NULL DEFAULT NULL COMMENT '设备剩余电量',
  `EV` decimal(10, 1) NULL DEFAULT NULL COMMENT '设备工作电压',
  `st` int NULL DEFAULT NULL COMMENT '采集数据状态',
  `lon` decimal(15, 6) NULL DEFAULT NULL COMMENT '经度（测站/设备）',
  `lat` decimal(15, 6) NULL DEFAULT NULL COMMENT '纬度（测站/设备）',
  `X` decimal(15, 3) NULL DEFAULT NULL COMMENT '北坐标（测站/测点）',
  `Y` decimal(15, 3) NULL DEFAULT NULL COMMENT '东坐标（测站/测点）',
  `Z` decimal(15, 3) NULL DEFAULT NULL COMMENT 'Z坐标（高程，测站/测点）',
  `hrz_dis_n` decimal(15, 4) NULL DEFAULT NULL COMMENT '水平位移（北向）',
  `hrz_dis_e` decimal(15, 4) NULL DEFAULT NULL COMMENT '水平位移（东向）',
  `vrt_dis` decimal(15, 4) NULL DEFAULT NULL COMMENT '垂直位移（Z方向）',
  `ts_prism_id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '棱镜/测点编号',
  `ts_hrz_angle` decimal(15, 4) NULL DEFAULT NULL COMMENT '水平角',
  `ts_vrt_angle` decimal(15, 4) NULL DEFAULT NULL COMMENT '竖直角',
  `ts_slope_dist` decimal(15, 4) NULL DEFAULT NULL COMMENT '斜距',
  `ts_hrz_dist` decimal(15, 4) NULL DEFAULT NULL COMMENT '平距',
  `ts_vrt_dist` decimal(15, 4) NULL DEFAULT NULL COMMENT '高差',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_deform_total_station_eid`(`eid` ASC) USING BTREE,
  INDEX `idx_deform_total_station_dt`(`dt` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 11 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of deform_total_station
-- ----------------------------
INSERT INTO `deform_total_station` VALUES (1, 'TS-equip001', '全站仪（TS-1201，0.5角秒,1mm+1ppm）-001', '边坡坡顶测点1（观测墩）', 'STN-01', 1781913600, 54, 12.5, 0, 112.547709, 37.883316, 4428965.944, 545194.881, 186.013, 0.0024, -0.0001, 0.0014, 'P-01', 322.3380, 85.4409, 82.1153, 107.3283, -4.4332);
INSERT INTO `deform_total_station` VALUES (2, 'TS-equip001', '全站仪（TS-1201，0.5角秒,1mm+1ppm）-001', '边坡坡顶测点1（观测墩）', 'STN-01', 1782000000, 95, 12.7, 1, 112.547709, 37.883316, 4428286.896, 545270.220, 197.853, 0.0004, 0.0013, -0.0010, 'P-01', 264.3338, 81.1409, 159.5744, 76.1966, -2.2787);
INSERT INTO `deform_total_station` VALUES (3, 'TS-equip002', '全站仪（TS-1201，0.5角秒,1mm+1ppm）-002', '大坝坝顶测点2（强制对中基座）', 'STN-02', 1781913600, 92, 12.2, 1, 112.476589, 37.968744, 4428524.558, 545316.735, 169.763, 0.0016, 0.0005, -0.0044, 'P-02', 32.2117, 99.9030, 138.4763, 95.1701, -4.1385);
INSERT INTO `deform_total_station` VALUES (4, 'TS-equip002', '全站仪（TS-1201，0.5角秒,1mm+1ppm）-002', '大坝坝顶测点2（强制对中基座）', 'STN-02', 1782000000, 61, 11.9, 0, 112.476589, 37.968744, 4428778.698, 545712.710, 199.320, -0.0042, 0.0013, -0.0020, 'P-02', 97.8530, 99.0284, 65.9662, 77.8769, -2.0433);
INSERT INTO `deform_total_station` VALUES (5, 'TS-equip003', '全站仪（TS-1201，0.5角秒,1mm+1ppm）-003', '隧道口测点3（基岩标）', 'STN-03', 1781913600, 87, 11.6, 1, 112.476657, 37.883466, 4428010.951, 545781.390, 186.404, 0.0015, -0.0040, 0.0029, 'P-03', 209.8837, 96.0740, 159.6613, 177.3844, 2.1402);
INSERT INTO `deform_total_station` VALUES (6, 'TS-equip003', '全站仪（TS-1201，0.5角秒,1mm+1ppm）-003', '隧道口测点3（基岩标）', 'STN-03', 1782000000, 62, 11.5, 1, 112.476657, 37.883466, 4428467.368, 545605.684, 169.164, 0.0010, 0.0041, -0.0026, 'P-03', 68.4874, 92.9129, 188.6711, 85.1286, -2.2928);
INSERT INTO `deform_total_station` VALUES (7, 'TS-equip004', '全站仪（TS-1201，0.5角秒,1mm+1ppm）-004', '大坝坝顶测点4（强制对中基座）', 'STN-04', 1781913600, 73, 11.6, 0, 112.521032, 37.829185, 4428203.237, 545089.715, 157.371, -0.0025, -0.0018, 0.0042, 'P-04', 147.8172, 96.8987, 54.8722, 121.4098, -0.0571);
INSERT INTO `deform_total_station` VALUES (8, 'TS-equip004', '全站仪（TS-1201，0.5角秒,1mm+1ppm）-004', '大坝坝顶测点4（强制对中基座）', 'STN-04', 1782000000, 57, 12.8, 1, 112.521032, 37.829185, 4428399.127, 545664.883, 152.715, -0.0012, 0.0042, -0.0023, 'P-04', 149.3935, 81.5610, 142.6875, 180.8737, -0.6672);
INSERT INTO `deform_total_station` VALUES (9, 'TS-equip005', '全站仪（TS-1201，0.5角秒,1mm+1ppm）-005', '大坝坝顶测点5（强制对中基座）', 'STN-05', 1781913600, 91, 11.7, 0, 112.539151, 37.810337, 4428313.815, 545918.869, 166.661, 0.0033, -0.0035, 0.0024, 'P-05', 188.4897, 92.4058, 117.0405, 132.2594, -4.5015);
INSERT INTO `deform_total_station` VALUES (10, 'TS-equip005', '全站仪（TS-1201，0.5角秒,1mm+1ppm）-005', '大坝坝顶测点5（强制对中基座）', 'STN-05', 1782000000, 82, 12.5, 0, 112.539151, 37.810337, 4428680.268, 545919.608, 197.656, 0.0042, -0.0031, 0.0032, 'P-05', 45.6941, 91.4397, 186.3412, 150.6669, 1.5268);

-- ----------------------------
-- Table structure for flow_array_radar
-- ----------------------------
DROP TABLE IF EXISTS `flow_array_radar`;
CREATE TABLE `flow_array_radar`  (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `eid` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备唯一编号',
  `equip_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备名称/型号',
  `install_addr` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备安装地址',
  `lon` decimal(15, 6) NULL DEFAULT NULL COMMENT '经度',
  `lat` decimal(15, 6) NULL DEFAULT NULL COMMENT '纬度',
  `alt` decimal(15, 3) NULL DEFAULT NULL COMMENT '设备安装高程',
  `dt` bigint NULL DEFAULT NULL COMMENT '采集时间戳',
  `E` int NULL DEFAULT NULL COMMENT '设备剩余电量',
  `EV` decimal(10, 1) NULL DEFAULT NULL COMMENT '设备工作电压',
  `st` int NULL DEFAULT NULL COMMENT '采集数据状态',
  `cid` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '采集通道ID',
  `create_time` datetime NULL DEFAULT NULL COMMENT '数据入库时间',
  `Q_inst` decimal(15, 3) NULL DEFAULT NULL COMMENT '瞬时流量',
  `Q_total` decimal(12, 2) NULL DEFAULT NULL COMMENT '累积流量',
  `V_avg` decimal(15, 3) NULL DEFAULT NULL COMMENT '断面平均流速',
  `ar_array_num` int NULL DEFAULT NULL COMMENT '阵列雷达单元数量',
  `ar_beam_angle` decimal(12, 2) NULL DEFAULT NULL COMMENT '雷达波束角',
  `ar_freq` decimal(10, 1) NULL DEFAULT NULL COMMENT '雷达工作频率',
  `ar_v_array` json NULL COMMENT '各垂线流速（n为阵列单元数）',
  `ar_water_level` decimal(15, 3) NULL DEFAULT NULL COMMENT '雷达监测水位',
  `ar_section_area` decimal(15, 3) NULL DEFAULT NULL COMMENT '过水断面面积',
  `ar_flow_dir` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '水流方向',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_flow_array_radar_eid`(`eid` ASC) USING BTREE,
  INDEX `idx_flow_array_radar_dt`(`dt` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 11 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of flow_array_radar
-- ----------------------------
INSERT INTO `flow_array_radar` VALUES (1, 'AR-equip001', '阵列式非接触雷达流量计（300W-QX-AR）-001', '某某渡槽1#流量监测点', 112.563783, 37.870657, 800.984, 1781913600, 38, 12.1, 0, 'AR-ch01', '2026-06-20 08:00:00', 12.967, 135515.97, 0.874, 8, 22.75, 24.0, '[1.559, 0.519, 2.215, 2.264, 2.029, 0.693, 1.107, 1.445]', 2.989, 11.677, '1');
INSERT INTO `flow_array_radar` VALUES (2, 'AR-equip001', '阵列式非接触雷达流量计（300W-QX-AR）-001', '某某渡槽1#流量监测点', 112.563783, 37.870657, 800.984, 1782000000, 52, 12.6, 1, 'AR-ch01', '2026-06-21 08:00:00', 27.437, 180087.93, 1.936, 7, 22.79, 24.0, '[1.346, 2.428, 0.886, 1.236, 1.616, 0.864, 0.652]', 2.829, 18.103, '0');
INSERT INTO `flow_array_radar` VALUES (3, 'AR-equip002', '阵列式非接触雷达流量计（300W-QX-AR）-002', '某某河干流监测断面-2（左岸）', 112.502709, 37.988234, 783.996, 1781913600, 40, 11.7, 0, 'AR-ch02', '2026-06-20 08:00:00', 27.852, 155576.15, 2.454, 4, 22.58, 24.0, '[1.573, 1.067, 1.526, 1.304]', 7.105, 5.118, '0');
INSERT INTO `flow_array_radar` VALUES (4, 'AR-equip002', '阵列式非接触雷达流量计（300W-QX-AR）-002', '某某河干流监测断面-2（左岸）', 112.502709, 37.988234, 783.996, 1782000000, 85, 11.8, 0, 'AR-ch02', '2026-06-21 08:00:00', 8.718, 103648.24, 0.925, 7, 16.92, 24.0, '[1.724, 0.789, 2.287, 0.8, 2.318, 1.478, 2.205]', 3.635, 16.269, '0');
INSERT INTO `flow_array_radar` VALUES (5, 'AR-equip003', '阵列式非接触雷达流量计（300W-QX-AR）-003', '某某河干流监测断面-3（左岸）', 112.408065, 37.942078, 812.991, 1781913600, 76, 12.0, 1, 'AR-ch03', '2026-06-20 08:00:00', 39.546, 136641.68, 2.741, 5, 13.50, 24.0, '[0.727, 2.035, 2.117, 2.088, 2.121]', 2.160, 8.465, '1');
INSERT INTO `flow_array_radar` VALUES (6, 'AR-equip003', '阵列式非接触雷达流量计（300W-QX-AR）-003', '某某河干流监测断面-3（左岸）', 112.408065, 37.942078, 812.991, 1782000000, 54, 11.5, 0, 'AR-ch03', '2026-06-21 08:00:00', 5.018, 151522.92, 1.665, 4, 17.64, 24.0, '[1.425, 2.212, 1.86, 1.751]', 5.444, 6.722, '0');
INSERT INTO `flow_array_radar` VALUES (7, 'AR-equip004', '阵列式非接触雷达流量计（300W-QX-AR）-004', '某某河干流监测断面-4（左岸）', 112.555712, 37.976454, 793.935, 1781913600, 59, 12.1, 1, 'AR-ch04', '2026-06-20 08:00:00', 36.300, 145910.37, 2.679, 8, 21.74, 24.0, '[0.711, 1.874, 1.148, 1.619, 1.066, 0.923, 1.6, 2.173]', 7.492, 8.764, '1');
INSERT INTO `flow_array_radar` VALUES (8, 'AR-equip004', '阵列式非接触雷达流量计（300W-QX-AR）-004', '某某河干流监测断面-4（左岸）', 112.555712, 37.976454, 793.935, 1782000000, 45, 12.5, 1, 'AR-ch04', '2026-06-21 08:00:00', 33.700, 141747.92, 1.968, 4, 13.37, 24.0, '[0.656, 2.073, 2.308, 1.484]', 2.369, 10.961, '0');
INSERT INTO `flow_array_radar` VALUES (9, 'AR-equip005', '阵列式非接触雷达流量计（300W-QX-AR）-005', '某某渡槽5#流量监测点', 112.582836, 37.897241, 806.963, 1781913600, 62, 11.9, 0, 'AR-ch05', '2026-06-20 08:00:00', 29.578, 190333.42, 2.015, 7, 11.51, 24.0, '[0.568, 1.176, 1.389, 0.984, 1.286, 0.768, 1.634]', 4.492, 17.292, '1');
INSERT INTO `flow_array_radar` VALUES (10, 'AR-equip005', '阵列式非接触雷达流量计（300W-QX-AR）-005', '某某渡槽5#流量监测点', 112.582836, 37.897241, 806.963, 1782000000, 68, 12.3, 0, 'AR-ch05', '2026-06-21 08:00:00', 5.155, 100360.35, 2.622, 3, 24.98, 24.0, '[1.16, 2.376, 1.022]', 3.145, 5.244, '1');

-- ----------------------------
-- Table structure for flow_radar_level
-- ----------------------------
DROP TABLE IF EXISTS `flow_radar_level`;
CREATE TABLE `flow_radar_level`  (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `eid` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备唯一编号',
  `equip_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备名称',
  `install_addr` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备安装地址（文字）',
  `lon` decimal(15, 6) NULL DEFAULT NULL COMMENT '经度',
  `lat` decimal(15, 6) NULL DEFAULT NULL COMMENT '纬度',
  `alt` decimal(15, 3) NULL DEFAULT NULL COMMENT '设备安装高程',
  `dt` bigint NULL DEFAULT NULL COMMENT '采集时间戳',
  `E` int NULL DEFAULT NULL COMMENT '设备剩余电量',
  `EV` decimal(10, 1) NULL DEFAULT NULL COMMENT '设备工作电压',
  `SSP` decimal(15, 3) NULL DEFAULT NULL COMMENT '传感器设置高度',
  `RV` decimal(15, 3) NULL DEFAULT NULL COMMENT '雷达采集空高',
  `L` decimal(15, 3) NULL DEFAULT NULL COMMENT '监测液位',
  `st` int NULL DEFAULT NULL COMMENT '采集数据状态',
  `cid` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '采集通道ID',
  `create_time` datetime NULL DEFAULT NULL COMMENT '数据入库时间',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_flow_radar_level_eid`(`eid` ASC) USING BTREE,
  INDEX `idx_flow_radar_level_dt`(`dt` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 11 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of flow_radar_level
-- ----------------------------
INSERT INTO `flow_radar_level` VALUES (1, 'RADAR-equip001', '雷达液位计-001', '某某闸站1#水位监测点', 112.518225, 37.928096, 797.670, 1781913600, 73, 12.0, 5.447, 1.826, 3.621, 0, 'RADAR-ch01', '2026-06-20 08:00:00');
INSERT INTO `flow_radar_level` VALUES (2, 'RADAR-equip001', '雷达液位计-001', '某某闸站1#水位监测点', 112.518225, 37.928096, 797.670, 1782000000, 58, 12.6, 7.349, 4.588, 2.761, 0, 'RADAR-ch01', '2026-06-21 08:00:00');
INSERT INTO `flow_radar_level` VALUES (3, 'RADAR-equip002', '雷达液位计-002', '某某水库坝前2#水位站', 112.523868, 37.869012, 790.059, 1781913600, 66, 12.4, 9.436, 1.560, 7.876, 0, 'RADAR-ch02', '2026-06-20 08:00:00');
INSERT INTO `flow_radar_level` VALUES (4, 'RADAR-equip002', '雷达液位计-002', '某某水库坝前2#水位站', 112.523868, 37.869012, 790.059, 1782000000, 80, 12.3, 7.388, 2.737, 4.651, 1, 'RADAR-ch02', '2026-06-21 08:00:00');
INSERT INTO `flow_radar_level` VALUES (5, 'RADAR-equip003', '雷达液位计-003', '某某水库坝前3#水位站', 112.402044, 37.806966, 813.552, 1781913600, 95, 12.3, 8.260, 1.543, 6.717, 0, 'RADAR-ch03', '2026-06-20 08:00:00');
INSERT INTO `flow_radar_level` VALUES (6, 'RADAR-equip003', '雷达液位计-003', '某某水库坝前3#水位站', 112.402044, 37.806966, 813.552, 1782000000, 31, 12.6, 6.558, 2.500, 4.058, 1, 'RADAR-ch03', '2026-06-21 08:00:00');
INSERT INTO `flow_radar_level` VALUES (7, 'RADAR-equip004', '雷达液位计-004', '某某水库坝前4#水位站', 112.546998, 37.897551, 784.039, 1781913600, 74, 12.8, 9.226, 1.299, 7.927, 0, 'RADAR-ch04', '2026-06-20 08:00:00');
INSERT INTO `flow_radar_level` VALUES (8, 'RADAR-equip004', '雷达液位计-004', '某某水库坝前4#水位站', 112.546998, 37.897551, 784.039, 1782000000, 43, 12.0, 8.461, 3.572, 4.889, 1, 'RADAR-ch04', '2026-06-21 08:00:00');
INSERT INTO `flow_radar_level` VALUES (9, 'RADAR-equip005', '雷达液位计-005', '某某河干流监测点-5（左岸）', 112.573440, 37.974165, 794.812, 1781913600, 65, 12.1, 5.726, 3.899, 1.827, 0, 'RADAR-ch05', '2026-06-20 08:00:00');
INSERT INTO `flow_radar_level` VALUES (10, 'RADAR-equip005', '雷达液位计-005', '某某河干流监测点-5（左岸）', 112.573440, 37.974165, 794.812, 1782000000, 48, 12.6, 6.600, 2.302, 4.298, 0, 'RADAR-ch05', '2026-06-21 08:00:00');

-- ----------------------------
-- Table structure for flow_tof_meter
-- ----------------------------
DROP TABLE IF EXISTS `flow_tof_meter`;
CREATE TABLE `flow_tof_meter`  (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `eid` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备唯一编号',
  `equip_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备名称/型号',
  `install_addr` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '设备安装地址',
  `lon` decimal(15, 6) NULL DEFAULT NULL COMMENT '经度',
  `lat` decimal(15, 6) NULL DEFAULT NULL COMMENT '纬度',
  `alt` decimal(15, 3) NULL DEFAULT NULL COMMENT '设备安装高程',
  `dt` bigint NULL DEFAULT NULL COMMENT '采集时间戳',
  `E` int NULL DEFAULT NULL COMMENT '设备剩余电量',
  `EV` decimal(10, 1) NULL DEFAULT NULL COMMENT '设备工作电压',
  `st` int NULL DEFAULT NULL COMMENT '采集数据状态',
  `cid` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '采集通道ID',
  `create_time` datetime NULL DEFAULT NULL COMMENT '数据入库时间',
  `Q_inst` decimal(15, 3) NULL DEFAULT NULL COMMENT '瞬时流量',
  `Q_total` decimal(12, 2) NULL DEFAULT NULL COMMENT '累积流量',
  `V_avg` decimal(15, 3) NULL DEFAULT NULL COMMENT '鱼道平均流速',
  `td_channel_num` int NULL DEFAULT NULL COMMENT '超声波声道数',
  `td_media_temp` decimal(10, 1) NULL DEFAULT NULL COMMENT '介质温度',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_flow_tof_meter_eid`(`eid` ASC) USING BTREE,
  INDEX `idx_flow_tof_meter_dt`(`dt` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 11 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of flow_tof_meter
-- ----------------------------
INSERT INTO `flow_tof_meter` VALUES (1, 'TD-equip001', '超声波时差流量计（Alpha3000）-001', '某某管道1#流量监测点', 112.407292, 37.849919, 810.692, 1781913600, 84, 12.2, 0, 'TD-ch01', '2026-06-20 08:00:00', 125.431, 143728.11, 2.367, 6, 16.9);
INSERT INTO `flow_tof_meter` VALUES (2, 'TD-equip001', '超声波时差流量计（Alpha3000）-001', '某某管道1#流量监测点', 112.407292, 37.849919, 810.692, 1782000000, 53, 11.8, 1, 'TD-ch01', '2026-06-21 08:00:00', 553.857, 112333.12, 0.547, 8, 18.1);
INSERT INTO `flow_tof_meter` VALUES (3, 'TD-equip002', '超声波时差流量计（Alpha3000）-002', '某某河干流2#流量站', 112.544632, 37.877887, 799.514, 1781913600, 73, 12.1, 0, 'TD-ch02', '2026-06-20 08:00:00', 384.260, 157500.43, 1.055, 5, 22.3);
INSERT INTO `flow_tof_meter` VALUES (4, 'TD-equip002', '超声波时差流量计（Alpha3000）-002', '某某河干流2#流量站', 112.544632, 37.877887, 799.514, 1782000000, 82, 11.7, 0, 'TD-ch02', '2026-06-21 08:00:00', 306.362, 119938.59, 1.258, 4, 15.9);
INSERT INTO `flow_tof_meter` VALUES (5, 'TD-equip003', '超声波时差流量计（Alpha3000）-003', '某某管道3#流量监测点', 112.510118, 37.932761, 812.216, 1781913600, 87, 12.2, 0, 'TD-ch03', '2026-06-20 08:00:00', 686.097, 123933.25, 2.484, 3, 23.8);
INSERT INTO `flow_tof_meter` VALUES (6, 'TD-equip003', '超声波时差流量计（Alpha3000）-003', '某某管道3#流量监测点', 112.510118, 37.932761, 812.216, 1782000000, 40, 11.9, 1, 'TD-ch03', '2026-06-21 08:00:00', 163.202, 103775.53, 1.238, 4, 22.6);
INSERT INTO `flow_tof_meter` VALUES (7, 'TD-equip004', '超声波时差流量计（Alpha3000）-004', '某某河干流4#流量站', 112.572986, 37.852732, 802.093, 1781913600, 71, 11.8, 0, 'TD-ch04', '2026-06-20 08:00:00', 501.458, 107761.06, 1.277, 5, 22.1);
INSERT INTO `flow_tof_meter` VALUES (8, 'TD-equip004', '超声波时差流量计（Alpha3000）-004', '某某河干流4#流量站', 112.572986, 37.852732, 802.093, 1782000000, 95, 12.1, 0, 'TD-ch04', '2026-06-21 08:00:00', 784.234, 193410.71, 2.294, 8, 17.6);
INSERT INTO `flow_tof_meter` VALUES (9, 'TD-equip005', '超声波时差流量计（Alpha3000）-005', '某某管道5#流量监测点', 112.472791, 37.959769, 817.093, 1781913600, 68, 12.4, 0, 'TD-ch05', '2026-06-20 08:00:00', 786.992, 197802.86, 1.864, 6, 19.9);
INSERT INTO `flow_tof_meter` VALUES (10, 'TD-equip005', '超声波时差流量计（Alpha3000）-005', '某某管道5#流量监测点', 112.472791, 37.959769, 817.093, 1782000000, 73, 11.5, 0, 'TD-ch05', '2026-06-21 08:00:00', 106.385, 183822.30, 1.718, 2, 18.2);

SET FOREIGN_KEY_CHECKS = 1;
