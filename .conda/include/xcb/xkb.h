/*
 * This file generated automatically from xkb.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_xkb_API XCB xkb API
 * @brief xkb XCB Protocol Implementation.
 * @{
 **/

#ifndef __XKB_H
#define __XKB_H

#include "xcb.h"
#include "xproto.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_XKB_MAJOR_VERSION 1
#define XCB_XKB_MINOR_VERSION 0

extern xcb_extension_t xcb_xkb_id;

typedef enum xcb_xkb_const_t {
    XCB_XKB_CONST_MAX_LEGAL_KEY_CODE = 255,
    XCB_XKB_CONST_PER_KEY_BIT_ARRAY_SIZE = 32,
    XCB_XKB_CONST_KEY_NAME_LENGTH = 4
} xcb_xkb_const_t;

typedef enum xcb_xkb_event_type_t {
    XCB_XKB_EVENT_TYPE_NEW_KEYBOARD_NOTIFY = 1,
    XCB_XKB_EVENT_TYPE_MAP_NOTIFY = 2,
    XCB_XKB_EVENT_TYPE_STATE_NOTIFY = 4,
    XCB_XKB_EVENT_TYPE_CONTROLS_NOTIFY = 8,
    XCB_XKB_EVENT_TYPE_INDICATOR_STATE_NOTIFY = 16,
    XCB_XKB_EVENT_TYPE_INDICATOR_MAP_NOTIFY = 32,
    XCB_XKB_EVENT_TYPE_NAMES_NOTIFY = 64,
    XCB_XKB_EVENT_TYPE_COMPAT_MAP_NOTIFY = 128,
    XCB_XKB_EVENT_TYPE_BELL_NOTIFY = 256,
    XCB_XKB_EVENT_TYPE_ACTION_MESSAGE = 512,
    XCB_XKB_EVENT_TYPE_ACCESS_X_NOTIFY = 1024,
    XCB_XKB_EVENT_TYPE_EXTENSION_DEVICE_NOTIFY = 2048
} xcb_xkb_event_type_t;

typedef enum xcb_xkb_nkn_detail_t {
    XCB_XKB_NKN_DETAIL_KEYCODES = 1,
    XCB_XKB_NKN_DETAIL_GEOMETRY = 2,
    XCB_XKB_NKN_DETAIL_DEVICE_ID = 4
} xcb_xkb_nkn_detail_t;

typedef enum xcb_xkb_axn_detail_t {
    XCB_XKB_AXN_DETAIL_SK_PRESS = 1,
    XCB_XKB_AXN_DETAIL_SK_ACCEPT = 2,
    XCB_XKB_AXN_DETAIL_SK_REJECT = 4,
    XCB_XKB_AXN_DETAIL_SK_RELEASE = 8,
    XCB_XKB_AXN_DETAIL_BK_ACCEPT = 16,
    XCB_XKB_AXN_DETAIL_BK_REJECT = 32,
    XCB_XKB_AXN_DETAIL_AXK_WARNING = 64
} xcb_xkb_axn_detail_t;

typedef enum xcb_xkb_map_part_t {
    XCB_XKB_MAP_PART_KEY_TYPES = 1,
    XCB_XKB_MAP_PART_KEY_SYMS = 2,
    XCB_XKB_MAP_PART_MODIFIER_MAP = 4,
    XCB_XKB_MAP_PART_EXPLICIT_COMPONENTS = 8,
    XCB_XKB_MAP_PART_KEY_ACTIONS = 16,
    XCB_XKB_MAP_PART_KEY_BEHAVIORS = 32,
    XCB_XKB_MAP_PART_VIRTUAL_MODS = 64,
    XCB_XKB_MAP_PART_VIRTUAL_MOD_MAP = 128
} xcb_xkb_map_part_t;

typedef enum xcb_xkb_set_map_flags_t {
    XCB_XKB_SET_MAP_FLAGS_RESIZE_TYPES = 1,
    XCB_XKB_SET_MAP_FLAGS_RECOMPUTE_ACTIONS = 2
} xcb_xkb_set_map_flags_t;

typedef enum xcb_xkb_state_part_t {
    XCB_XKB_STATE_PART_MODIFIER_STATE = 1,
    XCB_XKB_STATE_PART_MODIFIER_BASE = 2,
    XCB_XKB_STATE_PART_MODIFIER_LATCH = 4,
    XCB_XKB_STATE_PART_MODIFIER_LOCK = 8,
    XCB_XKB_STATE_PART_GROUP_STATE = 16,
    XCB_XKB_STATE_PART_GROUP_BASE = 32,
    XCB_XKB_STATE_PART_GROUP_LATCH = 64,
    XCB_XKB_STATE_PART_GROUP_LOCK = 128,
    XCB_XKB_STATE_PART_COMPAT_STATE = 256,
    XCB_XKB_STATE_PART_GRAB_MODS = 512,
    XCB_XKB_STATE_PART_COMPAT_GRAB_MODS = 1024,
    XCB_XKB_STATE_PART_LOOKUP_MODS = 2048,
    XCB_XKB_STATE_PART_COMPAT_LOOKUP_MODS = 4096,
    XCB_XKB_STATE_PART_POINTER_BUTTONS = 8192
} xcb_xkb_state_part_t;

typedef enum xcb_xkb_bool_ctrl_t {
    XCB_XKB_BOOL_CTRL_REPEAT_KEYS = 1,
    XCB_XKB_BOOL_CTRL_SLOW_KEYS = 2,
    XCB_XKB_BOOL_CTRL_BOUNCE_KEYS = 4,
    XCB_XKB_BOOL_CTRL_STICKY_KEYS = 8,
    XCB_XKB_BOOL_CTRL_MOUSE_KEYS = 16,
    XCB_XKB_BOOL_CTRL_MOUSE_KEYS_ACCEL = 32,
    XCB_XKB_BOOL_CTRL_ACCESS_X_KEYS = 64,
    XCB_XKB_BOOL_CTRL_ACCESS_X_TIMEOUT_MASK = 128,
    XCB_XKB_BOOL_CTRL_ACCESS_X_FEEDBACK_MASK = 256,
    XCB_XKB_BOOL_CTRL_AUDIBLE_BELL_MASK = 512,
    XCB_XKB_BOOL_CTRL_OVERLAY_1_MASK = 1024,
    XCB_XKB_BOOL_CTRL_OVERLAY_2_MASK = 2048,
    XCB_XKB_BOOL_CTRL_IGNORE_GROUP_LOCK_MASK = 4096
} xcb_xkb_bool_ctrl_t;

typedef enum xcb_xkb_control_t {
    XCB_XKB_CONTROL_GROUPS_WRAP = 134217728,
    XCB_XKB_CONTROL_INTERNAL_MODS = 268435456,
    XCB_XKB_CONTROL_IGNORE_LOCK_MODS = 536870912,
    XCB_XKB_CONTROL_PER_KEY_REPEAT = 1073741824,
    XCB_XKB_CONTROL_CONTROLS_ENABLED = 2147483648
} xcb_xkb_control_t;

typedef enum xcb_xkb_ax_option_t {
    XCB_XKB_AX_OPTION_SK_PRESS_FB = 1,
    XCB_XKB_AX_OPTION_SK_ACCEPT_FB = 2,
    XCB_XKB_AX_OPTION_FEATURE_FB = 4,
    XCB_XKB_AX_OPTION_SLOW_WARN_FB = 8,
    XCB_XKB_AX_OPTION_INDICATOR_FB = 16,
    XCB_XKB_AX_OPTION_STICKY_KEYS_FB = 32,
    XCB_XKB_AX_OPTION_TWO_KEYS = 64,
    XCB_XKB_AX_OPTION_LATCH_TO_LOCK = 128,
    XCB_XKB_AX_OPTION_SK_RELEASE_FB = 256,
    XCB_XKB_AX_OPTION_SK_REJECT_FB = 512,
    XCB_XKB_AX_OPTION_BK_REJECT_FB = 1024,
    XCB_XKB_AX_OPTION_DUMB_BELL = 2048
} xcb_xkb_ax_option_t;

typedef uint16_t xcb_xkb_device_spec_t;

/**
 * @brief xcb_xkb_device_spec_iterator_t
 **/
typedef struct xcb_xkb_device_spec_iterator_t {
    xcb_xkb_device_spec_t *data;
    int                    rem;
    int                    index;
} xcb_xkb_device_spec_iterator_t;

typedef enum xcb_xkb_led_class_result_t {
    XCB_XKB_LED_CLASS_RESULT_KBD_FEEDBACK_CLASS = 0,
    XCB_XKB_LED_CLASS_RESULT_LED_FEEDBACK_CLASS = 4
} xcb_xkb_led_class_result_t;

typedef enum xcb_xkb_led_class_t {
    XCB_XKB_LED_CLASS_KBD_FEEDBACK_CLASS = 0,
    XCB_XKB_LED_CLASS_LED_FEEDBACK_CLASS = 4,
    XCB_XKB_LED_CLASS_DFLT_XI_CLASS = 768,
    XCB_XKB_LED_CLASS_ALL_XI_CLASSES = 1280
} xcb_xkb_led_class_t;

typedef uint16_t xcb_xkb_led_class_spec_t;

/**
 * @brief xcb_xkb_led_class_spec_iterator_t
 **/
typedef struct xcb_xkb_led_class_spec_iterator_t {
    xcb_xkb_led_class_spec_t *data;
    int                       rem;
    int                       index;
} xcb_xkb_led_class_spec_iterator_t;

typedef enum xcb_xkb_bell_class_result_t {
    XCB_XKB_BELL_CLASS_RESULT_KBD_FEEDBACK_CLASS = 0,
    XCB_XKB_BELL_CLASS_RESULT_BELL_FEEDBACK_CLASS = 5
} xcb_xkb_bell_class_result_t;

typedef enum xcb_xkb_bell_class_t {
    XCB_XKB_BELL_CLASS_KBD_FEEDBACK_CLASS = 0,
    XCB_XKB_BELL_CLASS_BELL_FEEDBACK_CLASS = 5,
    XCB_XKB_BELL_CLASS_DFLT_XI_CLASS = 768
} xcb_xkb_bell_class_t;

typedef uint16_t xcb_xkb_bell_class_spec_t;

/**
 * @brief xcb_xkb_bell_class_spec_iterator_t
 **/
typedef struct xcb_xkb_bell_class_spec_iterator_t {
    xcb_xkb_bell_class_spec_t *data;
    int                        rem;
    int                        index;
} xcb_xkb_bell_class_spec_iterator_t;

typedef enum xcb_xkb_id_t {
    XCB_XKB_ID_USE_CORE_KBD = 256,
    XCB_XKB_ID_USE_CORE_PTR = 512,
    XCB_XKB_ID_DFLT_XI_CLASS = 768,
    XCB_XKB_ID_DFLT_XI_ID = 1024,
    XCB_XKB_ID_ALL_XI_CLASS = 1280,
    XCB_XKB_ID_ALL_XI_ID = 1536,
    XCB_XKB_ID_XI_NONE = 65280
} xcb_xkb_id_t;

typedef uint16_t xcb_xkb_id_spec_t;

/**
 * @brief xcb_xkb_id_spec_iterator_t
 **/
typedef struct xcb_xkb_id_spec_iterator_t {
    xcb_xkb_id_spec_t *data;
    int                rem;
    int                index;
} xcb_xkb_id_spec_iterator_t;

typedef enum xcb_xkb_group_t {
    XCB_XKB_GROUP_1 = 0,
    XCB_XKB_GROUP_2 = 1,
    XCB_XKB_GROUP_3 = 2,
    XCB_XKB_GROUP_4 = 3
} xcb_xkb_group_t;

typedef enum xcb_xkb_groups_t {
    XCB_XKB_GROUPS_ANY = 254,
    XCB_XKB_GROUPS_ALL = 255
} xcb_xkb_groups_t;

typedef enum xcb_xkb_set_of_group_t {
    XCB_XKB_SET_OF_GROUP_GROUP_1 = 1,
    XCB_XKB_SET_OF_GROUP_GROUP_2 = 2,
    XCB_XKB_SET_OF_GROUP_GROUP_3 = 4,
    XCB_XKB_SET_OF_GROUP_GROUP_4 = 8
} xcb_xkb_set_of_group_t;

typedef enum xcb_xkb_set_of_groups_t {
    XCB_XKB_SET_OF_GROUPS_ANY = 128
} xcb_xkb_set_of_groups_t;

typedef enum xcb_xkb_groups_wrap_t {
    XCB_XKB_GROUPS_WRAP_WRAP_INTO_RANGE = 0,
    XCB_XKB_GROUPS_WRAP_CLAMP_INTO_RANGE = 64,
    XCB_XKB_GROUPS_WRAP_REDIRECT_INTO_RANGE = 128
} xcb_xkb_groups_wrap_t;

typedef enum xcb_xkb_v_mods_high_t {
    XCB_XKB_V_MODS_HIGH_15 = 128,
    XCB_XKB_V_MODS_HIGH_14 = 64,
    XCB_XKB_V_MODS_HIGH_13 = 32,
    XCB_XKB_V_MODS_HIGH_12 = 16,
    XCB_XKB_V_MODS_HIGH_11 = 8,
    XCB_XKB_V_MODS_HIGH_10 = 4,
    XCB_XKB_V_MODS_HIGH_9 = 2,
    XCB_XKB_V_MODS_HIGH_8 = 1
} xcb_xkb_v_mods_high_t;

typedef enum xcb_xkb_v_mods_low_t {
    XCB_XKB_V_MODS_LOW_7 = 128,
    XCB_XKB_V_MODS_LOW_6 = 64,
    XCB_XKB_V_MODS_LOW_5 = 32,
    XCB_XKB_V_MODS_LOW_4 = 16,
    XCB_XKB_V_MODS_LOW_3 = 8,
    XCB_XKB_V_MODS_LOW_2 = 4,
    XCB_XKB_V_MODS_LOW_1 = 2,
    XCB_XKB_V_MODS_LOW_0 = 1
} xcb_xkb_v_mods_low_t;

typedef enum xcb_xkb_v_mod_t {
    XCB_XKB_V_MOD_15 = 32768,
    XCB_XKB_V_MOD_14 = 16384,
    XCB_XKB_V_MOD_13 = 8192,
    XCB_XKB_V_MOD_12 = 4096,
    XCB_XKB_V_MOD_11 = 2048,
    XCB_XKB_V_MOD_10 = 1024,
    XCB_XKB_V_MOD_9 = 512,
    XCB_XKB_V_MOD_8 = 256,
    XCB_XKB_V_MOD_7 = 128,
    XCB_XKB_V_MOD_6 = 64,
    XCB_XKB_V_MOD_5 = 32,
    XCB_XKB_V_MOD_4 = 16,
    XCB_XKB_V_MOD_3 = 8,
    XCB_XKB_V_MOD_2 = 4,
    XCB_XKB_V_MOD_1 = 2,
    XCB_XKB_V_MOD_0 = 1
} xcb_xkb_v_mod_t;

typedef enum xcb_xkb_explicit_t {
    XCB_XKB_EXPLICIT_V_MOD_MAP = 128,
    XCB_XKB_EXPLICIT_BEHAVIOR = 64,
    XCB_XKB_EXPLICIT_AUTO_REPEAT = 32,
    XCB_XKB_EXPLICIT_INTERPRET = 16,
    XCB_XKB_EXPLICIT_KEY_TYPE_4 = 8,
    XCB_XKB_EXPLICIT_KEY_TYPE_3 = 4,
    XCB_XKB_EXPLICIT_KEY_TYPE_2 = 2,
    XCB_XKB_EXPLICIT_KEY_TYPE_1 = 1
} xcb_xkb_explicit_t;

typedef enum xcb_xkb_sym_interpret_match_t {
    XCB_XKB_SYM_INTERPRET_MATCH_NONE_OF = 0,
    XCB_XKB_SYM_INTERPRET_MATCH_ANY_OF_OR_NONE = 1,
    XCB_XKB_SYM_INTERPRET_MATCH_ANY_OF = 2,
    XCB_XKB_SYM_INTERPRET_MATCH_ALL_OF = 3,
    XCB_XKB_SYM_INTERPRET_MATCH_EXACTLY = 4
} xcb_xkb_sym_interpret_match_t;

typedef enum xcb_xkb_sym_interp_match_t {
    XCB_XKB_SYM_INTERP_MATCH_LEVEL_ONE_ONLY = 128,
    XCB_XKB_SYM_INTERP_MATCH_OP_MASK = 127
} xcb_xkb_sym_interp_match_t;

typedef enum xcb_xkb_im_flag_t {
    XCB_XKB_IM_FLAG_NO_EXPLICIT = 128,
    XCB_XKB_IM_FLAG_NO_AUTOMATIC = 64,
    XCB_XKB_IM_FLAG_LED_DRIVES_KB = 32
} xcb_xkb_im_flag_t;

typedef enum xcb_xkb_im_mods_which_t {
    XCB_XKB_IM_MODS_WHICH_USE_COMPAT = 16,
    XCB_XKB_IM_MODS_WHICH_USE_EFFECTIVE = 8,
    XCB_XKB_IM_MODS_WHICH_USE_LOCKED = 4,
    XCB_XKB_IM_MODS_WHICH_USE_LATCHED = 2,
    XCB_XKB_IM_MODS_WHICH_USE_BASE = 1
} xcb_xkb_im_mods_which_t;

typedef enum xcb_xkb_im_groups_which_t {
    XCB_XKB_IM_GROUPS_WHICH_USE_COMPAT = 16,
    XCB_XKB_IM_GROUPS_WHICH_USE_EFFECTIVE = 8,
    XCB_XKB_IM_GROUPS_WHICH_USE_LOCKED = 4,
    XCB_XKB_IM_GROUPS_WHICH_USE_LATCHED = 2,
    XCB_XKB_IM_GROUPS_WHICH_USE_BASE = 1
} xcb_xkb_im_groups_which_t;

/**
 * @brief xcb_xkb_indicator_map_t
 **/
typedef struct xcb_xkb_indicator_map_t {
    uint8_t  flags;
    uint8_t  whichGroups;
    uint8_t  groups;
    uint8_t  whichMods;
    uint8_t  mods;
    uint8_t  realMods;
    uint16_t vmods;
    uint32_t ctrls;
} xcb_xkb_indicator_map_t;

/**
 * @brief xcb_xkb_indicator_map_iterator_t
 **/
typedef struct xcb_xkb_indicator_map_iterator_t {
    xcb_xkb_indicator_map_t *data;
    int                      rem;
    int                      index;
} xcb_xkb_indicator_map_iterator_t;

typedef enum xcb_xkb_cm_detail_t {
    XCB_XKB_CM_DETAIL_SYM_INTERP = 1,
    XCB_XKB_CM_DETAIL_GROUP_COMPAT = 2
} xcb_xkb_cm_detail_t;

typedef enum xcb_xkb_name_detail_t {
    XCB_XKB_NAME_DETAIL_KEYCODES = 1,
    XCB_XKB_NAME_DETAIL_GEOMETRY = 2,
    XCB_XKB_NAME_DETAIL_SYMBOLS = 4,
    XCB_XKB_NAME_DETAIL_PHYS_SYMBOLS = 8,
    XCB_XKB_NAME_DETAIL_TYPES = 16,
    XCB_XKB_NAME_DETAIL_COMPAT = 32,
    XCB_XKB_NAME_DETAIL_KEY_TYPE_NAMES = 64,
    XCB_XKB_NAME_DETAIL_KT_LEVEL_NAMES = 128,
    XCB_XKB_NAME_DETAIL_INDICATOR_NAMES = 256,
    XCB_XKB_NAME_DETAIL_KEY_NAMES = 512,
    XCB_XKB_NAME_DETAIL_KEY_ALIASES = 1024,
    XCB_XKB_NAME_DETAIL_VIRTUAL_MOD_NAMES = 2048,
    XCB_XKB_NAME_DETAIL_GROUP_NAMES = 4096,
    XCB_XKB_NAME_DETAIL_RG_NAMES = 8192
} xcb_xkb_name_detail_t;

typedef enum xcb_xkb_gbn_detail_t {
    XCB_XKB_GBN_DETAIL_TYPES = 1,
    XCB_XKB_GBN_DETAIL_COMPAT_MAP = 2,
    XCB_XKB_GBN_DETAIL_CLIENT_SYMBOLS = 4,
    XCB_XKB_GBN_DETAIL_SERVER_SYMBOLS = 8,
    XCB_XKB_GBN_DETAIL_INDICATOR_MAPS = 16,
    XCB_XKB_GBN_DETAIL_KEY_NAMES = 32,
    XCB_XKB_GBN_DETAIL_GEOMETRY = 64,
    XCB_XKB_GBN_DETAIL_OTHER_NAMES = 128
} xcb_xkb_gbn_detail_t;

typedef enum xcb_xkb_xi_feature_t {
    XCB_XKB_XI_FEATURE_KEYBOARDS = 1,
    XCB_XKB_XI_FEATURE_BUTTON_ACTIONS = 2,
    XCB_XKB_XI_FEATURE_INDICATOR_NAMES = 4,
    XCB_XKB_XI_FEATURE_INDICATOR_MAPS = 8,
    XCB_XKB_XI_FEATURE_INDICATOR_STATE = 16
} xcb_xkb_xi_feature_t;

typedef enum xcb_xkb_per_client_flag_t {
    XCB_XKB_PER_CLIENT_FLAG_DETECTABLE_AUTO_REPEAT = 1,
    XCB_XKB_PER_CLIENT_FLAG_GRABS_USE_XKB_STATE = 2,
    XCB_XKB_PER_CLIENT_FLAG_AUTO_RESET_CONTROLS = 4,
    XCB_XKB_PER_CLIENT_FLAG_LOOKUP_STATE_WHEN_GRABBED = 8,
    XCB_XKB_PER_CLIENT_FLAG_SEND_EVENT_USES_XKB_STATE = 16
} xcb_xkb_per_client_flag_t;

/**
 * @brief xcb_xkb_mod_def_t
 **/
typedef struct xcb_xkb_mod_def_t {
    uint8_t  mask;
    uint8_t  realMods;
    uint16_t vmods;
} xcb_xkb_mod_def_t;

/**
 * @brief xcb_xkb_mod_def_iterator_t
 **/
typedef struct xcb_xkb_mod_def_iterator_t {
    xcb_xkb_mod_def_t *data;
    int                rem;
    int                index;
} xcb_xkb_mod_def_iterator_t;

/**
 * @brief xcb_xkb_key_name_t
 **/
typedef struct xcb_xkb_key_name_t {
    char name[4];
} xcb_xkb_key_name_t;

/**
 * @brief xcb_xkb_key_name_iterator_t
 **/
typedef struct xcb_xkb_key_name_iterator_t {
    xcb_xkb_key_name_t *data;
    int                 rem;
    int                 index;
} xcb_xkb_key_name_iterator_t;

/**
 * @brief xcb_xkb_key_alias_t
 **/
typedef struct xcb_xkb_key_alias_t {
    char real[4];
    char alias[4];
} xcb_xkb_key_alias_t;

/**
 * @brief xcb_xkb_key_alias_iterator_t
 **/
typedef struct xcb_xkb_key_alias_iterator_t {
    xcb_xkb_key_alias_t *data;
    int                  rem;
    int                  index;
} xcb_xkb_key_alias_iterator_t;

/**
 * @brief xcb_xkb_counted_string_16_t
 **/
typedef struct xcb_xkb_counted_string_16_t {
    uint16_t length;
} xcb_xkb_counted_string_16_t;

/**
 * @brief xcb_xkb_counted_string_16_iterator_t
 **/
typedef struct xcb_xkb_counted_string_16_iterator_t {
    xcb_xkb_counted_string_16_t *data;
    int                          rem;
    int                          index;
} xcb_xkb_counted_string_16_iterator_t;

/**
 * @brief xcb_xkb_kt_map_entry_t
 **/
typedef struct xcb_xkb_kt_map_entry_t {
    uint8_t  active;
    uint8_t  mods_mask;
    uint8_t  level;
    uint8_t  mods_mods;
    uint16_t mods_vmods;
    uint8_t  pad0[2];
} xcb_xkb_kt_map_entry_t;

/**
 * @brief xcb_xkb_kt_map_entry_iterator_t
 **/
typedef struct xcb_xkb_kt_map_entry_iterator_t {
    xcb_xkb_kt_map_entry_t *data;
    int                     rem;
    int                     index;
} xcb_xkb_kt_map_entry_iterator_t;

/**
 * @brief xcb_xkb_key_type_t
 **/
typedef struct xcb_xkb_key_type_t {
    uint8_t  mods_mask;
    uint8_t  mods_mods;
    uint16_t mods_vmods;
    uint8_t  numLevels;
    uint8_t  nMapEntries;
    uint8_t  hasPreserve;
    uint8_t  pad0;
} xcb_xkb_key_type_t;

/**
 * @brief xcb_xkb_key_type_iterator_t
 **/
typedef struct xcb_xkb_key_type_iterator_t {
    xcb_xkb_key_type_t *data;
    int                 rem;
    int                 index;
} xcb_xkb_key_type_iterator_t;

/**
 * @brief xcb_xkb_key_sym_map_t
 **/
typedef struct xcb_xkb_key_sym_map_t {
    uint8_t  kt_index[4];
    uint8_t  groupInfo;
    uint8_t  width;
    uint16_t nSyms;
} xcb_xkb_key_sym_map_t;

/**
 * @brief xcb_xkb_key_sym_map_iterator_t
 **/
typedef struct xcb_xkb_key_sym_map_iterator_t {
    xcb_xkb_key_sym_map_t *data;
    int                    rem;
    int                    index;
} xcb_xkb_key_sym_map_iterator_t;

/**
 * @brief xcb_xkb_common_behavior_t
 **/
typedef struct xcb_xkb_common_behavior_t {
    uint8_t type;
    uint8_t data;
} xcb_xkb_common_behavior_t;

/**
 * @brief xcb_xkb_common_behavior_iterator_t
 **/
typedef struct xcb_xkb_common_behavior_iterator_t {
    xcb_xkb_common_behavior_t *data;
    int                        rem;
    int                        index;
} xcb_xkb_common_behavior_iterator_t;

/**
 * @brief xcb_xkb_default_behavior_t
 **/
typedef struct xcb_xkb_default_behavior_t {
    uint8_t type;
    uint8_t pad0;
} xcb_xkb_default_behavior_t;

/**
 * @brief xcb_xkb_default_behavior_iterator_t
 **/
typedef struct xcb_xkb_default_behavior_iterator_t {
    xcb_xkb_default_behavior_t *data;
    int                         rem;
    int                         index;
} xcb_xkb_default_behavior_iterator_t;

/**
 * @brief xcb_xkb_lock_behavior_t
 **/
typedef struct xcb_xkb_lock_behavior_t {
    uint8_t type;
    uint8_t pad0;
} xcb_xkb_lock_behavior_t;

/**
 * @brief xcb_xkb_lock_behavior_iterator_t
 **/
typedef struct xcb_xkb_lock_behavior_iterator_t {
    xcb_xkb_lock_behavior_t *data;
    int                      rem;
    int                      index;
} xcb_xkb_lock_behavior_iterator_t;

/**
 * @brief xcb_xkb_radio_group_behavior_t
 **/
typedef struct xcb_xkb_radio_group_behavior_t {
    uint8_t type;
    uint8_t group;
} xcb_xkb_radio_group_behavior_t;

/**
 * @brief xcb_xkb_radio_group_behavior_iterator_t
 **/
typedef struct xcb_xkb_radio_group_behavior_iterator_t {
    xcb_xkb_radio_group_behavior_t *data;
    int                             rem;
    int                             index;
} xcb_xkb_radio_group_behavior_iterator_t;

/**
 * @brief xcb_xkb_overlay_behavior_t
 **/
typedef struct xcb_xkb_overlay_behavior_t {
    uint8_t       type;
    xcb_keycode_t key;
} xcb_xkb_overlay_behavior_t;

/**
 * @brief xcb_xkb_overlay_behavior_iterator_t
 **/
typedef struct xcb_xkb_overlay_behavior_iterator_t {
    xcb_xkb_overlay_behavior_t *data;
    int                         rem;
    int                         index;
} xcb_xkb_overlay_behavior_iterator_t;

/**
 * @brief xcb_xkb_permament_lock_behavior_t
 **/
typedef struct xcb_xkb_permament_lock_behavior_t {
    uint8_t type;
    uint8_t pad0;
} xcb_xkb_permament_lock_behavior_t;

/**
 * @brief xcb_xkb_permament_lock_behavior_iterator_t
 **/
typedef struct xcb_xkb_permament_lock_behavior_iterator_t {
    xcb_xkb_permament_lock_behavior_t *data;
    int                                rem;
    int                                index;
} xcb_xkb_permament_lock_behavior_iterator_t;

/**
 * @brief xcb_xkb_permament_radio_group_behavior_t
 **/
typedef struct xcb_xkb_permament_radio_group_behavior_t {
    uint8_t type;
    uint8_t group;
} xcb_xkb_permament_radio_group_behavior_t;

/**
 * @brief xcb_xkb_permament_radio_group_behavior_iterator_t
 **/
typedef struct xcb_xkb_permament_radio_group_behavior_iterator_t {
    xcb_xkb_permament_radio_group_behavior_t *data;
    int                                       rem;
    int                                       index;
} xcb_xkb_permament_radio_group_behavior_iterator_t;

/**
 * @brief xcb_xkb_permament_overlay_behavior_t
 **/
typedef struct xcb_xkb_permament_overlay_behavior_t {
    uint8_t       type;
    xcb_keycode_t key;
} xcb_xkb_permament_overlay_behavior_t;

/**
 * @brief xcb_xkb_permament_overlay_behavior_iterator_t
 **/
typedef struct xcb_xkb_permament_overlay_behavior_iterator_t {
    xcb_xkb_permament_overlay_behavior_t *data;
    int                                   rem;
    int                                   index;
} xcb_xkb_permament_overlay_behavior_iterator_t;

/**
 * @brief xcb_xkb_behavior_t
 **/
typedef union xcb_xkb_behavior_t {
    xcb_xkb_common_behavior_t                common;
    xcb_xkb_default_behavior_t               _default;
    xcb_xkb_lock_behavior_t                  lock;
    xcb_xkb_radio_group_behavior_t           radioGroup;
    xcb_xkb_overlay_behavior_t               overlay1;
    xcb_xkb_overlay_behavior_t               overlay2;
    xcb_xkb_permament_lock_behavior_t        permamentLock;
    xcb_xkb_permament_radio_group_behavior_t permamentRadioGroup;
    xcb_xkb_permament_overlay_behavior_t     permamentOverlay1;
    xcb_xkb_permament_overlay_behavior_t     permamentOverlay2;
    uint8_t                                  type;
} xcb_xkb_behavior_t;

/**
 * @brief xcb_xkb_behavior_iterator_t
 **/
typedef struct xcb_xkb_behavior_iterator_t {
    xcb_xkb_behavior_t *data;
    int                 rem;
    int                 index;
} xcb_xkb_behavior_iterator_t;

typedef enum xcb_xkb_behavior_type_t {
    XCB_XKB_BEHAVIOR_TYPE_DEFAULT = 0,
    XCB_XKB_BEHAVIOR_TYPE_LOCK = 1,
    XCB_XKB_BEHAVIOR_TYPE_RADIO_GROUP = 2,
    XCB_XKB_BEHAVIOR_TYPE_OVERLAY_1 = 3,
    XCB_XKB_BEHAVIOR_TYPE_OVERLAY_2 = 4,
    XCB_XKB_BEHAVIOR_TYPE_PERMAMENT_LOCK = 129,
    XCB_XKB_BEHAVIOR_TYPE_PERMAMENT_RADIO_GROUP = 130,
    XCB_XKB_BEHAVIOR_TYPE_PERMAMENT_OVERLAY_1 = 131,
    XCB_XKB_BEHAVIOR_TYPE_PERMAMENT_OVERLAY_2 = 132
} xcb_xkb_behavior_type_t;

/**
 * @brief xcb_xkb_set_behavior_t
 **/
typedef struct xcb_xkb_set_behavior_t {
    xcb_keycode_t      keycode;
    xcb_xkb_behavior_t behavior;
    uint8_t            pad0;
} xcb_xkb_set_behavior_t;

/**
 * @brief xcb_xkb_set_behavior_iterator_t
 **/
typedef struct xcb_xkb_set_behavior_iterator_t {
    xcb_xkb_set_behavior_t *data;
    int                     rem;
    int                     index;
} xcb_xkb_set_behavior_iterator_t;

/**
 * @brief xcb_xkb_set_explicit_t
 **/
typedef struct xcb_xkb_set_explicit_t {
    xcb_keycode_t keycode;
    uint8_t       explicit;
} xcb_xkb_set_explicit_t;

/**
 * @brief xcb_xkb_set_explicit_iterator_t
 **/
typedef struct xcb_xkb_set_explicit_iterator_t {
    xcb_xkb_set_explicit_t *data;
    int                     rem;
    int                     index;
} xcb_xkb_set_explicit_iterator_t;

/**
 * @brief xcb_xkb_key_mod_map_t
 **/
typedef struct xcb_xkb_key_mod_map_t {
    xcb_keycode_t keycode;
    uint8_t       mods;
} xcb_xkb_key_mod_map_t;

/**
 * @brief xcb_xkb_key_mod_map_iterator_t
 **/
typedef struct xcb_xkb_key_mod_map_iterator_t {
    xcb_xkb_key_mod_map_t *data;
    int                    rem;
    int                    index;
} xcb_xkb_key_mod_map_iterator_t;

/**
 * @brief xcb_xkb_key_v_mod_map_t
 **/
typedef struct xcb_xkb_key_v_mod_map_t {
    xcb_keycode_t keycode;
    uint8_t       pad0;
    uint16_t      vmods;
} xcb_xkb_key_v_mod_map_t;

/**
 * @brief xcb_xkb_key_v_mod_map_iterator_t
 **/
typedef struct xcb_xkb_key_v_mod_map_iterator_t {
    xcb_xkb_key_v_mod_map_t *data;
    int                      rem;
    int                      index;
} xcb_xkb_key_v_mod_map_iterator_t;

/**
 * @brief xcb_xkb_kt_set_map_entry_t
 **/
typedef struct xcb_xkb_kt_set_map_entry_t {
    uint8_t  level;
    uint8_t  realMods;
    uint16_t virtualMods;
} xcb_xkb_kt_set_map_entry_t;

/**
 * @brief xcb_xkb_kt_set_map_entry_iterator_t
 **/
typedef struct xcb_xkb_kt_set_map_entry_iterator_t {
    xcb_xkb_kt_set_map_entry_t *data;
    int                         rem;
    int                         index;
} xcb_xkb_kt_set_map_entry_iterator_t;

/**
 * @brief xcb_xkb_set_key_type_t
 **/
typedef struct xcb_xkb_set_key_type_t {
    uint8_t  mask;
    uint8_t  realMods;
    uint16_t virtualMods;
    uint8_t  numLevels;
    uint8_t  nMapEntries;
    uint8_t  preserve;
    uint8_t  pad0;
} xcb_xkb_set_key_type_t;

/**
 * @brief xcb_xkb_set_key_type_iterator_t
 **/
typedef struct xcb_xkb_set_key_type_iterator_t {
    xcb_xkb_set_key_type_t *data;
    int                     rem;
    int                     index;
} xcb_xkb_set_key_type_iterator_t;

typedef char xcb_xkb_string8_t;

/**
 * @brief xcb_xkb_string8_iterator_t
 **/
typedef struct xcb_xkb_string8_iterator_t {
    xcb_xkb_string8_t *data;
    int                rem;
    int                index;
} xcb_xkb_string8_iterator_t;

/**
 * @brief xcb_xkb_outline_t
 **/
typedef struct xcb_xkb_outline_t {
    uint8_t nPoints;
    uint8_t cornerRadius;
    uint8_t pad0[2];
} xcb_xkb_outline_t;

/**
 * @brief xcb_xkb_outline_iterator_t
 **/
typedef struct xcb_xkb_outline_iterator_t {
    xcb_xkb_outline_t *data;
    int                rem;
    int                index;
} xcb_xkb_outline_iterator_t;

/**
 * @brief xcb_xkb_shape_t
 **/
typedef struct xcb_xkb_shape_t {
    xcb_atom_t name;
    uint8_t    nOutlines;
    uint8_t    primaryNdx;
    uint8_t    approxNdx;
    uint8_t    pad0;
} xcb_xkb_shape_t;

/**
 * @brief xcb_xkb_shape_iterator_t
 **/
typedef struct xcb_xkb_shape_iterator_t {
    xcb_xkb_shape_t *data;
    int              rem;
    int              index;
} xcb_xkb_shape_iterator_t;

/**
 * @brief xcb_xkb_key_t
 **/
typedef struct xcb_xkb_key_t {
    xcb_xkb_string8_t name[4];
    int16_t           gap;
    uint8_t           shapeNdx;
    uint8_t           colorNdx;
} xcb_xkb_key_t;

/**
 * @brief xcb_xkb_key_iterator_t
 **/
typedef struct xcb_xkb_key_iterator_t {
    xcb_xkb_key_t *data;
    int            rem;
    int            index;
} xcb_xkb_key_iterator_t;

/**
 * @brief xcb_xkb_overlay_key_t
 **/
typedef struct xcb_xkb_overlay_key_t {
    xcb_xkb_string8_t over[4];
    xcb_xkb_string8_t under[4];
} xcb_xkb_overlay_key_t;

/**
 * @brief xcb_xkb_overlay_key_iterator_t
 **/
typedef struct xcb_xkb_overlay_key_iterator_t {
    xcb_xkb_overlay_key_t *data;
    int                    rem;
    int                    index;
} xcb_xkb_overlay_key_iterator_t;

/**
 * @brief xcb_xkb_overlay_row_t
 **/
typedef struct xcb_xkb_overlay_row_t {
    uint8_t rowUnder;
    uint8_t nKeys;
    uint8_t pad0[2];
} xcb_xkb_overlay_row_t;

/**
 * @brief xcb_xkb_overlay_row_iterator_t
 **/
typedef struct xcb_xkb_overlay_row_iterator_t {
    xcb_xkb_overlay_row_t *data;
    int                    rem;
    int                    index;
} xcb_xkb_overlay_row_iterator_t;

/**
 * @brief xcb_xkb_overlay_t
 **/
typedef struct xcb_xkb_overlay_t {
    xcb_atom_t name;
    uint8_t    nRows;
    uint8_t    pad0[3];
} xcb_xkb_overlay_t;

/**
 * @brief xcb_xkb_overlay_iterator_t
 **/
typedef struct xcb_xkb_overlay_iterator_t {
    xcb_xkb_overlay_t *data;
    int                rem;
    int                index;
} xcb_xkb_overlay_iterator_t;

/**
 * @brief xcb_xkb_row_t
 **/
typedef struct xcb_xkb_row_t {
    int16_t top;
    int16_t left;
    uint8_t nKeys;
    uint8_t vertical;
    uint8_t pad0[2];
} xcb_xkb_row_t;

/**
 * @brief xcb_xkb_row_iterator_t
 **/
typedef struct xcb_xkb_row_iterator_t {
    xcb_xkb_row_t *data;
    int            rem;
    int            index;
} xcb_xkb_row_iterator_t;

typedef enum xcb_xkb_doodad_type_t {
    XCB_XKB_DOODAD_TYPE_OUTLINE = 1,
    XCB_XKB_DOODAD_TYPE_SOLID = 2,
    XCB_XKB_DOODAD_TYPE_TEXT = 3,
    XCB_XKB_DOODAD_TYPE_INDICATOR = 4,
    XCB_XKB_DOODAD_TYPE_LOGO = 5
} xcb_xkb_doodad_type_t;

/**
 * @brief xcb_xkb_listing_t
 **/
typedef struct xcb_xkb_listing_t {
    uint16_t flags;
    uint16_t length;
} xcb_xkb_listing_t;

/**
 * @brief xcb_xkb_listing_iterator_t
 **/
typedef struct xcb_xkb_listing_iterator_t {
    xcb_xkb_listing_t *data;
    int                rem;
    int                index;
} xcb_xkb_listing_iterator_t;

/**
 * @brief xcb_xkb_device_led_info_t
 **/
typedef struct xcb_xkb_device_led_info_t {
    xcb_xkb_led_class_spec_t ledClass;
    xcb_xkb_id_spec_t        ledID;
    uint32_t                 namesPresent;
    uint32_t                 mapsPresent;
    uint32_t                 physIndicators;
    uint32_t                 state;
} xcb_xkb_device_led_info_t;

/**
 * @brief xcb_xkb_device_led_info_iterator_t
 **/
typedef struct xcb_xkb_device_led_info_iterator_t {
    xcb_xkb_device_led_info_t *data;
    int                        rem;
    int                        index;
} xcb_xkb_device_led_info_iterator_t;

typedef enum xcb_xkb_error_t {
    XCB_XKB_ERROR_BAD_DEVICE = 255,
    XCB_XKB_ERROR_BAD_CLASS = 254,
    XCB_XKB_ERROR_BAD_ID = 253
} xcb_xkb_error_t;

/** Opcode for xcb_xkb_keyboard. */
#define XCB_XKB_KEYBOARD 0

/**
 * @brief xcb_xkb_keyboard_error_t
 **/
typedef struct xcb_xkb_keyboard_error_t {
    uint8_t  response_type;
    uint8_t  error_code;
    uint16_t sequence;
    uint32_t value;
    uint16_t minorOpcode;
    uint8_t  majorOpcode;
    uint8_t  pad0[21];
} xcb_xkb_keyboard_error_t;

typedef enum xcb_xkb_sa_t {
    XCB_XKB_SA_CLEAR_LOCKS = 1,
    XCB_XKB_SA_LATCH_TO_LOCK = 2,
    XCB_XKB_SA_USE_MOD_MAP_MODS = 4,
    XCB_XKB_SA_GROUP_ABSOLUTE = 4
} xcb_xkb_sa_t;

typedef enum xcb_xkb_sa_type_t {
    XCB_XKB_SA_TYPE_NO_ACTION = 0,
    XCB_XKB_SA_TYPE_SET_MODS = 1,
    XCB_XKB_SA_TYPE_LATCH_MODS = 2,
    XCB_XKB_SA_TYPE_LOCK_MODS = 3,
    XCB_XKB_SA_TYPE_SET_GROUP = 4,
    XCB_XKB_SA_TYPE_LATCH_GROUP = 5,
    XCB_XKB_SA_TYPE_LOCK_GROUP = 6,
    XCB_XKB_SA_TYPE_MOVE_PTR = 7,
    XCB_XKB_SA_TYPE_PTR_BTN = 8,
    XCB_XKB_SA_TYPE_LOCK_PTR_BTN = 9,
    XCB_XKB_SA_TYPE_SET_PTR_DFLT = 10,
    XCB_XKB_SA_TYPE_ISO_LOCK = 11,
    XCB_XKB_SA_TYPE_TERMINATE = 12,
    XCB_XKB_SA_TYPE_SWITCH_SCREEN = 13,
    XCB_XKB_SA_TYPE_SET_CONTROLS = 14,
    XCB_XKB_SA_TYPE_LOCK_CONTROLS = 15,
    XCB_XKB_SA_TYPE_ACTION_MESSAGE = 16,
    XCB_XKB_SA_TYPE_REDIRECT_KEY = 17,
    XCB_XKB_SA_TYPE_DEVICE_BTN = 18,
    XCB_XKB_SA_TYPE_LOCK_DEVICE_BTN = 19,
    XCB_XKB_SA_TYPE_DEVICE_VALUATOR = 20
} xcb_xkb_sa_type_t;

/**
 * @brief xcb_xkb_sa_no_action_t
 **/
typedef struct xcb_xkb_sa_no_action_t {
    uint8_t type;
    uint8_t pad0[7];
} xcb_xkb_sa_no_action_t;

/**
 * @brief xcb_xkb_sa_no_action_iterator_t
 **/
typedef struct xcb_xkb_sa_no_action_iterator_t {
    xcb_xkb_sa_no_action_t *data;
    int                     rem;
    int                     index;
} xcb_xkb_sa_no_action_iterator_t;

/**
 * @brief xcb_xkb_sa_set_mods_t
 **/
typedef struct xcb_xkb_sa_set_mods_t {
    uint8_t type;
    uint8_t flags;
    uint8_t mask;
    uint8_t realMods;
    uint8_t vmodsHigh;
    uint8_t vmodsLow;
    uint8_t pad0[2];
} xcb_xkb_sa_set_mods_t;

/**
 * @brief xcb_xkb_sa_set_mods_iterator_t
 **/
typedef struct xcb_xkb_sa_set_mods_iterator_t {
    xcb_xkb_sa_set_mods_t *data;
    int                    rem;
    int                    index;
} xcb_xkb_sa_set_mods_iterator_t;

/**
 * @brief xcb_xkb_sa_latch_mods_t
 **/
typedef struct xcb_xkb_sa_latch_mods_t {
    uint8_t type;
    uint8_t flags;
    uint8_t mask;
    uint8_t realMods;
    uint8_t vmodsHigh;
    uint8_t vmodsLow;
    uint8_t pad0[2];
} xcb_xkb_sa_latch_mods_t;

/**
 * @brief xcb_xkb_sa_latch_mods_iterator_t
 **/
typedef struct xcb_xkb_sa_latch_mods_iterator_t {
    xcb_xkb_sa_latch_mods_t *data;
    int                      rem;
    int                      index;
} xcb_xkb_sa_latch_mods_iterator_t;

/**
 * @brief xcb_xkb_sa_lock_mods_t
 **/
typedef struct xcb_xkb_sa_lock_mods_t {
    uint8_t type;
    uint8_t flags;
    uint8_t mask;
    uint8_t realMods;
    uint8_t vmodsHigh;
    uint8_t vmodsLow;
    uint8_t pad0[2];
} xcb_xkb_sa_lock_mods_t;

/**
 * @brief xcb_xkb_sa_lock_mods_iterator_t
 **/
typedef struct xcb_xkb_sa_lock_mods_iterator_t {
    xcb_xkb_sa_lock_mods_t *data;
    int                     rem;
    int                     index;
} xcb_xkb_sa_lock_mods_iterator_t;

/**
 * @brief xcb_xkb_sa_set_group_t
 **/
typedef struct xcb_xkb_sa_set_group_t {
    uint8_t type;
    uint8_t flags;
    int8_t  group;
    uint8_t pad0[5];
} xcb_xkb_sa_set_group_t;

/**
 * @brief xcb_xkb_sa_set_group_iterator_t
 **/
typedef struct xcb_xkb_sa_set_group_iterator_t {
    xcb_xkb_sa_set_group_t *data;
    int                     rem;
    int                     index;
} xcb_xkb_sa_set_group_iterator_t;

/**
 * @brief xcb_xkb_sa_latch_group_t
 **/
typedef struct xcb_xkb_sa_latch_group_t {
    uint8_t type;
    uint8_t flags;
    int8_t  group;
    uint8_t pad0[5];
} xcb_xkb_sa_latch_group_t;

/**
 * @brief xcb_xkb_sa_latch_group_iterator_t
 **/
typedef struct xcb_xkb_sa_latch_group_iterator_t {
    xcb_xkb_sa_latch_group_t *data;
    int                       rem;
    int                       index;
} xcb_xkb_sa_latch_group_iterator_t;

/**
 * @brief xcb_xkb_sa_lock_group_t
 **/
typedef struct xcb_xkb_sa_lock_group_t {
    uint8_t type;
    uint8_t flags;
    int8_t  group;
    uint8_t pad0[5];
} xcb_xkb_sa_lock_group_t;

/**
 * @brief xcb_xkb_sa_lock_group_iterator_t
 **/
typedef struct xcb_xkb_sa_lock_group_iterator_t {
    xcb_xkb_sa_lock_group_t *data;
    int                      rem;
    int                      index;
} xcb_xkb_sa_lock_group_iterator_t;

typedef enum xcb_xkb_sa_move_ptr_flag_t {
    XCB_XKB_SA_MOVE_PTR_FLAG_NO_ACCELERATION = 1,
    XCB_XKB_SA_MOVE_PTR_FLAG_MOVE_ABSOLUTE_X = 2,
    XCB_XKB_SA_MOVE_PTR_FLAG_MOVE_ABSOLUTE_Y = 4
} xcb_xkb_sa_move_ptr_flag_t;

/**
 * @brief xcb_xkb_sa_move_ptr_t
 **/
typedef struct xcb_xkb_sa_move_ptr_t {
    uint8_t type;
    uint8_t flags;
    int8_t  xHigh;
    uint8_t xLow;
    int8_t  yHigh;
    uint8_t yLow;
    uint8_t pad0[2];
} xcb_xkb_sa_move_ptr_t;

/**
 * @brief xcb_xkb_sa_move_ptr_iterator_t
 **/
typedef struct xcb_xkb_sa_move_ptr_iterator_t {
    xcb_xkb_sa_move_ptr_t *data;
    int                    rem;
    int                    index;
} xcb_xkb_sa_move_ptr_iterator_t;

/**
 * @brief xcb_xkb_sa_ptr_btn_t
 **/
typedef struct xcb_xkb_sa_ptr_btn_t {
    uint8_t type;
    uint8_t flags;
    uint8_t count;
    uint8_t button;
    uint8_t pad0[4];
} xcb_xkb_sa_ptr_btn_t;

/**
 * @brief xcb_xkb_sa_ptr_btn_iterator_t
 **/
typedef struct xcb_xkb_sa_ptr_btn_iterator_t {
    xcb_xkb_sa_ptr_btn_t *data;
    int                   rem;
    int                   index;
} xcb_xkb_sa_ptr_btn_iterator_t;

/**
 * @brief xcb_xkb_sa_lock_ptr_btn_t
 **/
typedef struct xcb_xkb_sa_lock_ptr_btn_t {
    uint8_t type;
    uint8_t flags;
    uint8_t pad0;
    uint8_t button;
    uint8_t pad1[4];
} xcb_xkb_sa_lock_ptr_btn_t;

/**
 * @brief xcb_xkb_sa_lock_ptr_btn_iterator_t
 **/
typedef struct xcb_xkb_sa_lock_ptr_btn_iterator_t {
    xcb_xkb_sa_lock_ptr_btn_t *data;
    int                        rem;
    int                        index;
} xcb_xkb_sa_lock_ptr_btn_iterator_t;

typedef enum xcb_xkb_sa_set_ptr_dflt_flag_t {
    XCB_XKB_SA_SET_PTR_DFLT_FLAG_DFLT_BTN_ABSOLUTE = 4,
    XCB_XKB_SA_SET_PTR_DFLT_FLAG_AFFECT_DFLT_BUTTON = 1
} xcb_xkb_sa_set_ptr_dflt_flag_t;

/**
 * @brief xcb_xkb_sa_set_ptr_dflt_t
 **/
typedef struct xcb_xkb_sa_set_ptr_dflt_t {
    uint8_t type;
    uint8_t flags;
    uint8_t affect;
    int8_t  value;
    uint8_t pad0[4];
} xcb_xkb_sa_set_ptr_dflt_t;

/**
 * @brief xcb_xkb_sa_set_ptr_dflt_iterator_t
 **/
typedef struct xcb_xkb_sa_set_ptr_dflt_iterator_t {
    xcb_xkb_sa_set_ptr_dflt_t *data;
    int                        rem;
    int                        index;
} xcb_xkb_sa_set_ptr_dflt_iterator_t;

typedef enum xcb_xkb_sa_iso_lock_flag_t {
    XCB_XKB_SA_ISO_LOCK_FLAG_NO_LOCK = 1,
    XCB_XKB_SA_ISO_LOCK_FLAG_NO_UNLOCK = 2,
    XCB_XKB_SA_ISO_LOCK_FLAG_USE_MOD_MAP_MODS = 4,
    XCB_XKB_SA_ISO_LOCK_FLAG_GROUP_ABSOLUTE = 4,
    XCB_XKB_SA_ISO_LOCK_FLAG_ISO_DFLT_IS_GROUP = 8
} xcb_xkb_sa_iso_lock_flag_t;

typedef enum xcb_xkb_sa_iso_lock_no_affect_t {
    XCB_XKB_SA_ISO_LOCK_NO_AFFECT_CTRLS = 8,
    XCB_XKB_SA_ISO_LOCK_NO_AFFECT_PTR = 16,
    XCB_XKB_SA_ISO_LOCK_NO_AFFECT_GROUP = 32,
    XCB_XKB_SA_ISO_LOCK_NO_AFFECT_MODS = 64
} xcb_xkb_sa_iso_lock_no_affect_t;

/**
 * @brief xcb_xkb_sa_iso_lock_t
 **/
typedef struct xcb_xkb_sa_iso_lock_t {
    uint8_t type;
    uint8_t flags;
    uint8_t mask;
    uint8_t realMods;
    int8_t  group;
    uint8_t affect;
    uint8_t vmodsHigh;
    uint8_t vmodsLow;
} xcb_xkb_sa_iso_lock_t;

/**
 * @brief xcb_xkb_sa_iso_lock_iterator_t
 **/
typedef struct xcb_xkb_sa_iso_lock_iterator_t {
    xcb_xkb_sa_iso_lock_t *data;
    int                    rem;
    int                    index;
} xcb_xkb_sa_iso_lock_iterator_t;

/**
 * @brief xcb_xkb_sa_terminate_t
 **/
typedef struct xcb_xkb_sa_terminate_t {
    uint8_t type;
    uint8_t pad0[7];
} xcb_xkb_sa_terminate_t;

/**
 * @brief xcb_xkb_sa_terminate_iterator_t
 **/
typedef struct xcb_xkb_sa_terminate_iterator_t {
    xcb_xkb_sa_terminate_t *data;
    int                     rem;
    int                     index;
} xcb_xkb_sa_terminate_iterator_t;

typedef enum xcb_xkb_switch_screen_flag_t {
    XCB_XKB_SWITCH_SCREEN_FLAG_APPLICATION = 1,
    XCB_XKB_SWITCH_SCREEN_FLAG_ABSOLUTE = 4
} xcb_xkb_switch_screen_flag_t;

/**
 * @brief xcb_xkb_sa_switch_screen_t
 **/
typedef struct xcb_xkb_sa_switch_screen_t {
    uint8_t type;
    uint8_t flags;
    int8_t  newScreen;
    uint8_t pad0[5];
} xcb_xkb_sa_switch_screen_t;

/**
 * @brief xcb_xkb_sa_switch_screen_iterator_t
 **/
typedef struct xcb_xkb_sa_switch_screen_iterator_t {
    xcb_xkb_sa_switch_screen_t *data;
    int                         rem;
    int                         index;
} xcb_xkb_sa_switch_screen_iterator_t;

typedef enum xcb_xkb_bool_ctrls_high_t {
    XCB_XKB_BOOL_CTRLS_HIGH_ACCESS_X_FEEDBACK = 1,
    XCB_XKB_BOOL_CTRLS_HIGH_AUDIBLE_BELL = 2,
    XCB_XKB_BOOL_CTRLS_HIGH_OVERLAY_1 = 4,
    XCB_XKB_BOOL_CTRLS_HIGH_OVERLAY_2 = 8,
    XCB_XKB_BOOL_CTRLS_HIGH_IGNORE_GROUP_LOCK = 16
} xcb_xkb_bool_ctrls_high_t;

typedef enum xcb_xkb_bool_ctrls_low_t {
    XCB_XKB_BOOL_CTRLS_LOW_REPEAT_KEYS = 1,
    XCB_XKB_BOOL_CTRLS_LOW_SLOW_KEYS = 2,
    XCB_XKB_BOOL_CTRLS_LOW_BOUNCE_KEYS = 4,
    XCB_XKB_BOOL_CTRLS_LOW_STICKY_KEYS = 8,
    XCB_XKB_BOOL_CTRLS_LOW_MOUSE_KEYS = 16,
    XCB_XKB_BOOL_CTRLS_LOW_MOUSE_KEYS_ACCEL = 32,
    XCB_XKB_BOOL_CTRLS_LOW_ACCESS_X_KEYS = 64,
    XCB_XKB_BOOL_CTRLS_LOW_ACCESS_X_TIMEOUT = 128
} xcb_xkb_bool_ctrls_low_t;

/**
 * @brief xcb_xkb_sa_set_controls_t
 **/
typedef struct xcb_xkb_sa_set_controls_t {
    uint8_t type;
    uint8_t pad0[3];
    uint8_t boolCtrlsHigh;
    uint8_t boolCtrlsLow;
    uint8_t pad1[2];
} xcb_xkb_sa_set_controls_t;

/**
 * @brief xcb_xkb_sa_set_controls_iterator_t
 **/
typedef struct xcb_xkb_sa_set_controls_iterator_t {
    xcb_xkb_sa_set_controls_t *data;
    int                        rem;
    int                        index;
} xcb_xkb_sa_set_controls_iterator_t;

/**
 * @brief xcb_xkb_sa_lock_controls_t
 **/
typedef struct xcb_xkb_sa_lock_controls_t {
    uint8_t type;
    uint8_t pad0[3];
    uint8_t boolCtrlsHigh;
    uint8_t boolCtrlsLow;
    uint8_t pad1[2];
} xcb_xkb_sa_lock_controls_t;

/**
 * @brief xcb_xkb_sa_lock_controls_iterator_t
 **/
typedef struct xcb_xkb_sa_lock_controls_iterator_t {
    xcb_xkb_sa_lock_controls_t *data;
    int                         rem;
    int                         index;
} xcb_xkb_sa_lock_controls_iterator_t;

typedef enum xcb_xkb_action_message_flag_t {
    XCB_XKB_ACTION_MESSAGE_FLAG_ON_PRESS = 1,
    XCB_XKB_ACTION_MESSAGE_FLAG_ON_RELEASE = 2,
    XCB_XKB_ACTION_MESSAGE_FLAG_GEN_KEY_EVENT = 4
} xcb_xkb_action_message_flag_t;

/**
 * @brief xcb_xkb_sa_action_message_t
 **/
typedef struct xcb_xkb_sa_action_message_t {
    uint8_t type;
    uint8_t flags;
    uint8_t message[6];
} xcb_xkb_sa_action_message_t;

/**
 * @brief xcb_xkb_sa_action_message_iterator_t
 **/
typedef struct xcb_xkb_sa_action_message_iterator_t {
    xcb_xkb_sa_action_message_t *data;
    int                          rem;
    int                          index;
} xcb_xkb_sa_action_message_iterator_t;

/**
 * @brief xcb_xkb_sa_redirect_key_t
 **/
typedef struct xcb_xkb_sa_redirect_key_t {
    uint8_t       type;
    xcb_keycode_t newkey;
    uint8_t       mask;
    uint8_t       realModifiers;
    uint8_t       vmodsMaskHigh;
    uint8_t       vmodsMaskLow;
    uint8_t       vmodsHigh;
    uint8_t       vmodsLow;
} xcb_xkb_sa_redirect_key_t;

/**
 * @brief xcb_xkb_sa_redirect_key_iterator_t
 **/
typedef struct xcb_xkb_sa_redirect_key_iterator_t {
    xcb_xkb_sa_redirect_key_t *data;
    int                        rem;
    int                        index;
} xcb_xkb_sa_redirect_key_iterator_t;

/**
 * @brief xcb_xkb_sa_device_btn_t
 **/
typedef struct xcb_xkb_sa_device_btn_t {
    uint8_t type;
    uint8_t flags;
    uint8_t count;
    uint8_t button;
    uint8_t device;
    uint8_t pad0[3];
} xcb_xkb_sa_device_btn_t;

/**
 * @brief xcb_xkb_sa_device_btn_iterator_t
 **/
typedef struct xcb_xkb_sa_device_btn_iterator_t {
    xcb_xkb_sa_device_btn_t *data;
    int                      rem;
    int                      index;
} xcb_xkb_sa_device_btn_iterator_t;

typedef enum xcb_xkb_lock_device_flags_t {
    XCB_XKB_LOCK_DEVICE_FLAGS_NO_LOCK = 1,
    XCB_XKB_LOCK_DEVICE_FLAGS_NO_UNLOCK = 2
} xcb_xkb_lock_device_flags_t;

/**
 * @brief xcb_xkb_sa_lock_device_btn_t
 **/
typedef struct xcb_xkb_sa_lock_device_btn_t {
    uint8_t type;
    uint8_t flags;
    uint8_t pad0;
    uint8_t button;
    uint8_t device;
    uint8_t pad1[3];
} xcb_xkb_sa_lock_device_btn_t;

/**
 * @brief xcb_xkb_sa_lock_device_btn_iterator_t
 **/
typedef struct xcb_xkb_sa_lock_device_btn_iterator_t {
    xcb_xkb_sa_lock_device_btn_t *data;
    int                           rem;
    int                           index;
} xcb_xkb_sa_lock_device_btn_iterator_t;

typedef enum xcb_xkb_sa_val_what_t {
    XCB_XKB_SA_VAL_WHAT_IGNORE_VAL = 0,
    XCB_XKB_SA_VAL_WHAT_SET_VAL_MIN = 1,
    XCB_XKB_SA_VAL_WHAT_SET_VAL_CENTER = 2,
    XCB_XKB_SA_VAL_WHAT_SET_VAL_MAX = 3,
    XCB_XKB_SA_VAL_WHAT_SET_VAL_RELATIVE = 4,
    XCB_XKB_SA_VAL_WHAT_SET_VAL_ABSOLUTE = 5
} xcb_xkb_sa_val_what_t;

/**
 * @brief xcb_xkb_sa_device_valuator_t
 **/
typedef struct xcb_xkb_sa_device_valuator_t {
    uint8_t type;
    uint8_t device;
    uint8_t val1what;
    uint8_t val1index;
    uint8_t val1value;
    uint8_t val2what;
    uint8_t val2index;
    uint8_t val2value;
} xcb_xkb_sa_device_valuator_t;

/**
 * @brief xcb_xkb_sa_device_valuator_iterator_t
 **/
typedef struct xcb_xkb_sa_device_valuator_iterator_t {
    xcb_xkb_sa_device_valuator_t *data;
    int                           rem;
    int                           index;
} xcb_xkb_sa_device_valuator_iterator_t;

/**
 * @brief xcb_xkb_si_action_t
 **/
typedef struct xcb_xkb_si_action_t {
    uint8_t type;
    uint8_t data[7];
} xcb_xkb_si_action_t;

/**
 * @brief xcb_xkb_si_action_iterator_t
 **/
typedef struct xcb_xkb_si_action_iterator_t {
    xcb_xkb_si_action_t *data;
    int                  rem;
    int                  index;
} xcb_xkb_si_action_iterator_t;

/**
 * @brief xcb_xkb_sym_interpret_t
 **/
typedef struct xcb_xkb_sym_interpret_t {
    xcb_keysym_t        sym;
    uint8_t             mods;
    uint8_t             match;
    uint8_t             virtualMod;
    uint8_t             flags;
    xcb_xkb_si_action_t action;
} xcb_xkb_sym_interpret_t;

/**
 * @brief xcb_xkb_sym_interpret_iterator_t
 **/
typedef struct xcb_xkb_sym_interpret_iterator_t {
    xcb_xkb_sym_interpret_t *data;
    int                      rem;
    int                      index;
} xcb_xkb_sym_interpret_iterator_t;

/**
 * @brief xcb_xkb_action_t
 **/
typedef union xcb_xkb_action_t {
    xcb_xkb_sa_no_action_t       noaction;
    xcb_xkb_sa_set_mods_t        setmods;
    xcb_xkb_sa_latch_mods_t      latchmods;
    xcb_xkb_sa_lock_mods_t       lockmods;
    xcb_xkb_sa_set_group_t       setgroup;
    xcb_xkb_sa_latch_group_t     latchgroup;
    xcb_xkb_sa_lock_group_t      lockgroup;
    xcb_xkb_sa_move_ptr_t        moveptr;
    xcb_xkb_sa_ptr_btn_t         ptrbtn;
    xcb_xkb_sa_lock_ptr_btn_t    lockptrbtn;
    xcb_xkb_sa_set_ptr_dflt_t    setptrdflt;
    xcb_xkb_sa_iso_lock_t        isolock;
    xcb_xkb_sa_terminate_t       terminate;
    xcb_xkb_sa_switch_screen_t   switchscreen;
    xcb_xkb_sa_set_controls_t    setcontrols;
    xcb_xkb_sa_lock_controls_t   lockcontrols;
    xcb_xkb_sa_action_message_t  message;
    xcb_xkb_sa_redirect_key_t    redirect;
    xcb_xkb_sa_device_btn_t      devbtn;
    xcb_xkb_sa_lock_device_btn_t lockdevbtn;
    xcb_xkb_sa_device_valuator_t devval;
    uint8_t                      type;
} xcb_xkb_action_t;

/**
 * @brief xcb_xkb_action_iterator_t
 **/
typedef struct xcb_xkb_action_iterator_t {
    xcb_xkb_action_t *data;
    int               rem;
    int               index;
} xcb_xkb_action_iterator_t;

/**
 * @brief xcb_xkb_use_extension_cookie_t
 **/
typedef struct xcb_xkb_use_extension_cookie_t {
    unsigned int sequence;
} xcb_xkb_use_extension_cookie_t;

/** Opcode for xcb_xkb_use_extension. */
#define XCB_XKB_USE_EXTENSION 0

/**
 * @brief xcb_xkb_use_extension_request_t
 **/
typedef struct xcb_xkb_use_extension_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint16_t wantedMajor;
    uint16_t wantedMinor;
} xcb_xkb_use_extension_request_t;

/**
 * @brief xcb_xkb_use_extension_reply_t
 **/
typedef struct xcb_xkb_use_extension_reply_t {
    uint8_t  response_type;
    uint8_t  supported;
    uint16_t sequence;
    uint32_t length;
    uint16_t serverMajor;
    uint16_t serverMinor;
    uint8_t  pad0[20];
} xcb_xkb_use_extension_reply_t;

/**
 * @brief xcb_xkb_select_events_details_t
 **/
typedef struct xcb_xkb_select_events_details_t {
    uint16_t affectNewKeyboard;
    uint16_t newKeyboardDetails;
    uint16_t affectState;
    uint16_t stateDetails;
    uint32_t affectCtrls;
    uint32_t ctrlDetails;
    uint32_t affectIndicatorState;
    uint32_t indicatorStateDetails;
    uint32_t affectIndicatorMap;
    uint32_t indicatorMapDetails;
    uint16_t affectNames;
    uint16_t namesDetails;
    uint8_t  affectCompat;
    uint8_t  compatDetails;
    uint8_t  affectBell;
    uint8_t  bellDetails;
    uint8_t  affectMsgDetails;
    uint8_t  msgDetails;
    uint16_t affectAccessX;
    uint16_t accessXDetails;
    uint16_t affectExtDev;
    uint16_t extdevDetails;
} xcb_xkb_select_events_details_t;

/** Opcode for xcb_xkb_select_events. */
#define XCB_XKB_SELECT_EVENTS 1

/**
 * @brief xcb_xkb_select_events_request_t
 **/
typedef struct xcb_xkb_select_events_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint16_t              affectWhich;
    uint16_t              clear;
    uint16_t              selectAll;
    uint16_t              affectMap;
    uint16_t              map;
} xcb_xkb_select_events_request_t;

/** Opcode for xcb_xkb_bell. */
#define XCB_XKB_BELL 3

/**
 * @brief xcb_xkb_bell_request_t
 **/
typedef struct xcb_xkb_bell_request_t {
    uint8_t                   major_opcode;
    uint8_t                   minor_opcode;
    uint16_t                  length;
    xcb_xkb_device_spec_t     deviceSpec;
    xcb_xkb_bell_class_spec_t bellClass;
    xcb_xkb_id_spec_t         bellID;
    int8_t                    percent;
    uint8_t                   forceSound;
    uint8_t                   eventOnly;
    uint8_t                   pad0;
    int16_t                   pitch;
    int16_t                   duration;
    uint8_t                   pad1[2];
    xcb_atom_t                name;
    xcb_window_t              window;
} xcb_xkb_bell_request_t;

/**
 * @brief xcb_xkb_get_state_cookie_t
 **/
typedef struct xcb_xkb_get_state_cookie_t {
    unsigned int sequence;
} xcb_xkb_get_state_cookie_t;

/** Opcode for xcb_xkb_get_state. */
#define XCB_XKB_GET_STATE 4

/**
 * @brief xcb_xkb_get_state_request_t
 **/
typedef struct xcb_xkb_get_state_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint8_t               pad0[2];
} xcb_xkb_get_state_request_t;

/**
 * @brief xcb_xkb_get_state_reply_t
 **/
typedef struct xcb_xkb_get_state_reply_t {
    uint8_t  response_type;
    uint8_t  deviceID;
    uint16_t sequence;
    uint32_t length;
    uint8_t  mods;
    uint8_t  baseMods;
    uint8_t  latchedMods;
    uint8_t  lockedMods;
    uint8_t  group;
    uint8_t  lockedGroup;
    int16_t  baseGroup;
    int16_t  latchedGroup;
    uint8_t  compatState;
    uint8_t  grabMods;
    uint8_t  compatGrabMods;
    uint8_t  lookupMods;
    uint8_t  compatLookupMods;
    uint8_t  pad0;
    uint16_t ptrBtnState;
    uint8_t  pad1[6];
} xcb_xkb_get_state_reply_t;

/** Opcode for xcb_xkb_latch_lock_state. */
#define XCB_XKB_LATCH_LOCK_STATE 5

/**
 * @brief xcb_xkb_latch_lock_state_request_t
 **/
typedef struct xcb_xkb_latch_lock_state_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint8_t               affectModLocks;
    uint8_t               modLocks;
    uint8_t               lockGroup;
    uint8_t               groupLock;
    uint8_t               affectModLatches;
    uint8_t               pad0;
    uint8_t               pad1;
    uint8_t               latchGroup;
    uint16_t              groupLatch;
} xcb_xkb_latch_lock_state_request_t;

/**
 * @brief xcb_xkb_get_controls_cookie_t
 **/
typedef struct xcb_xkb_get_controls_cookie_t {
    unsigned int sequence;
} xcb_xkb_get_controls_cookie_t;

/** Opcode for xcb_xkb_get_controls. */
#define XCB_XKB_GET_CONTROLS 6

/**
 * @brief xcb_xkb_get_controls_request_t
 **/
typedef struct xcb_xkb_get_controls_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint8_t               pad0[2];
} xcb_xkb_get_controls_request_t;

/**
 * @brief xcb_xkb_get_controls_reply_t
 **/
typedef struct xcb_xkb_get_controls_reply_t {
    uint8_t  response_type;
    uint8_t  deviceID;
    uint16_t sequence;
    uint32_t length;
    uint8_t  mouseKeysDfltBtn;
    uint8_t  numGroups;
    uint8_t  groupsWrap;
    uint8_t  internalModsMask;
    uint8_t  ignoreLockModsMask;
    uint8_t  internalModsRealMods;
    uint8_t  ignoreLockModsRealMods;
    uint8_t  pad0;
    uint16_t internalModsVmods;
    uint16_t ignoreLockModsVmods;
    uint16_t repeatDelay;
    uint16_t repeatInterval;
    uint16_t slowKeysDelay;
    uint16_t debounceDelay;
    uint16_t mouseKeysDelay;
    uint16_t mouseKeysInterval;
    uint16_t mouseKeysTimeToMax;
    uint16_t mouseKeysMaxSpeed;
    int16_t  mouseKeysCurve;
    uint16_t accessXOption;
    uint16_t accessXTimeout;
    uint16_t accessXTimeoutOptionsMask;
    uint16_t accessXTimeoutOptionsValues;
    uint8_t  pad1[2];
    uint32_t accessXTimeoutMask;
    uint32_t accessXTimeoutValues;
    uint32_t enabledControls;
    uint8_t  perKeyRepeat[32];
} xcb_xkb_get_controls_reply_t;

/** Opcode for xcb_xkb_set_controls. */
#define XCB_XKB_SET_CONTROLS 7

/**
 * @brief xcb_xkb_set_controls_request_t
 **/
typedef struct xcb_xkb_set_controls_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint8_t               affectInternalRealMods;
    uint8_t               internalRealMods;
    uint8_t               affectIgnoreLockRealMods;
    uint8_t               ignoreLockRealMods;
    uint16_t              affectInternalVirtualMods;
    uint16_t              internalVirtualMods;
    uint16_t              affectIgnoreLockVirtualMods;
    uint16_t              ignoreLockVirtualMods;
    uint8_t               mouseKeysDfltBtn;
    uint8_t               groupsWrap;
    uint16_t              accessXOptions;
    uint8_t               pad0[2];
    uint32_t              affectEnabledControls;
    uint32_t              enabledControls;
    uint32_t              changeControls;
    uint16_t              repeatDelay;
    uint16_t              repeatInterval;
    uint16_t              slowKeysDelay;
    uint16_t              debounceDelay;
    uint16_t              mouseKeysDelay;
    uint16_t              mouseKeysInterval;
    uint16_t              mouseKeysTimeToMax;
    uint16_t              mouseKeysMaxSpeed;
    int16_t               mouseKeysCurve;
    uint16_t              accessXTimeout;
    uint32_t              accessXTimeoutMask;
    uint32_t              accessXTimeoutValues;
    uint16_t              accessXTimeoutOptionsMask;
    uint16_t              accessXTimeoutOptionsValues;
    uint8_t               perKeyRepeat[32];
} xcb_xkb_set_controls_request_t;

/**
 * @brief xcb_xkb_get_map_cookie_t
 **/
typedef struct xcb_xkb_get_map_cookie_t {
    unsigned int sequence;
} xcb_xkb_get_map_cookie_t;

/** Opcode for xcb_xkb_get_map. */
#define XCB_XKB_GET_MAP 8

/**
 * @brief xcb_xkb_get_map_request_t
 **/
typedef struct xcb_xkb_get_map_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint16_t              full;
    uint16_t              partial;
    uint8_t               firstType;
    uint8_t               nTypes;
    xcb_keycode_t         firstKeySym;
    uint8_t               nKeySyms;
    xcb_keycode_t         firstKeyAction;
    uint8_t               nKeyActions;
    xcb_keycode_t         firstKeyBehavior;
    uint8_t               nKeyBehaviors;
    uint16_t              virtualMods;
    xcb_keycode_t         firstKeyExplicit;
    uint8_t               nKeyExplicit;
    xcb_keycode_t         firstModMapKey;
    uint8_t               nModMapKeys;
    xcb_keycode_t         firstVModMapKey;
    uint8_t               nVModMapKeys;
    uint8_t               pad0[2];
} xcb_xkb_get_map_request_t;

/**
 * @brief xcb_xkb_get_map_map_t
 **/
typedef struct xcb_xkb_get_map_map_t {
    xcb_xkb_key_type_t      *types_rtrn;
    xcb_xkb_key_sym_map_t   *syms_rtrn;
    uint8_t                 *acts_rtrn_count;
    uint8_t                 *pad2;
    xcb_xkb_action_t        *acts_rtrn_acts;
    xcb_xkb_set_behavior_t  *behaviors_rtrn;
    uint8_t                 *vmods_rtrn;
    uint8_t                 *pad3;
    xcb_xkb_set_explicit_t  *explicit_rtrn;
    uint8_t                 *pad4;
    xcb_xkb_key_mod_map_t   *modmap_rtrn;
    uint8_t                 *pad5;
    xcb_xkb_key_v_mod_map_t *vmodmap_rtrn;
} xcb_xkb_get_map_map_t;

/**
 * @brief xcb_xkb_get_map_reply_t
 **/
typedef struct xcb_xkb_get_map_reply_t {
    uint8_t       response_type;
    uint8_t       deviceID;
    uint16_t      sequence;
    uint32_t      length;
    uint8_t       pad0[2];
    xcb_keycode_t minKeyCode;
    xcb_keycode_t maxKeyCode;
    uint16_t      present;
    uint8_t       firstType;
    uint8_t       nTypes;
    uint8_t       totalTypes;
    xcb_keycode_t firstKeySym;
    uint16_t      totalSyms;
    uint8_t       nKeySyms;
    xcb_keycode_t firstKeyAction;
    uint16_t      totalActions;
    uint8_t       nKeyActions;
    xcb_keycode_t firstKeyBehavior;
    uint8_t       nKeyBehaviors;
    uint8_t       totalKeyBehaviors;
    xcb_keycode_t firstKeyExplicit;
    uint8_t       nKeyExplicit;
    uint8_t       totalKeyExplicit;
    xcb_keycode_t firstModMapKey;
    uint8_t       nModMapKeys;
    uint8_t       totalModMapKeys;
    xcb_keycode_t firstVModMapKey;
    uint8_t       nVModMapKeys;
    uint8_t       totalVModMapKeys;
    uint8_t       pad1;
    uint16_t      virtualMods;
} xcb_xkb_get_map_reply_t;

/**
 * @brief xcb_xkb_set_map_values_t
 **/
typedef struct xcb_xkb_set_map_values_t {
    xcb_xkb_set_key_type_t  *types;
    xcb_xkb_key_sym_map_t   *syms;
    uint8_t                 *actionsCount;
    xcb_xkb_action_t        *actions;
    xcb_xkb_set_behavior_t  *behaviors;
    uint8_t                 *vmods;
    xcb_xkb_set_explicit_t  *explicit;
    xcb_xkb_key_mod_map_t   *modmap;
    xcb_xkb_key_v_mod_map_t *vmodmap;
} xcb_xkb_set_map_values_t;

/** Opcode for xcb_xkb_set_map. */
#define XCB_XKB_SET_MAP 9

/**
 * @brief xcb_xkb_set_map_request_t
 **/
typedef struct xcb_xkb_set_map_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint16_t              present;
    uint16_t              flags;
    xcb_keycode_t         minKeyCode;
    xcb_keycode_t         maxKeyCode;
    uint8_t               firstType;
    uint8_t               nTypes;
    xcb_keycode_t         firstKeySym;
    uint8_t               nKeySyms;
    uint16_t              totalSyms;
    xcb_keycode_t         firstKeyAction;
    uint8_t               nKeyActions;
    uint16_t              totalActions;
    xcb_keycode_t         firstKeyBehavior;
    uint8_t               nKeyBehaviors;
    uint8_t               totalKeyBehaviors;
    xcb_keycode_t         firstKeyExplicit;
    uint8_t               nKeyExplicit;
    uint8_t               totalKeyExplicit;
    xcb_keycode_t         firstModMapKey;
    uint8_t               nModMapKeys;
    uint8_t               totalModMapKeys;
    xcb_keycode_t         firstVModMapKey;
    uint8_t               nVModMapKeys;
    uint8_t               totalVModMapKeys;
    uint16_t              virtualMods;
} xcb_xkb_set_map_request_t;

/**
 * @brief xcb_xkb_get_compat_map_cookie_t
 **/
typedef struct xcb_xkb_get_compat_map_cookie_t {
    unsigned int sequence;
} xcb_xkb_get_compat_map_cookie_t;

/** Opcode for xcb_xkb_get_compat_map. */
#define XCB_XKB_GET_COMPAT_MAP 10

/**
 * @brief xcb_xkb_get_compat_map_request_t
 **/
typedef struct xcb_xkb_get_compat_map_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint8_t               groups;
    uint8_t               getAllSI;
    uint16_t              firstSI;
    uint16_t              nSI;
} xcb_xkb_get_compat_map_request_t;

/**
 * @brief xcb_xkb_get_compat_map_reply_t
 **/
typedef struct xcb_xkb_get_compat_map_reply_t {
    uint8_t  response_type;
    uint8_t  deviceID;
    uint16_t sequence;
    uint32_t length;
    uint8_t  groupsRtrn;
    uint8_t  pad0;
    uint16_t firstSIRtrn;
    uint16_t nSIRtrn;
    uint16_t nTotalSI;
    uint8_t  pad1[16];
} xcb_xkb_get_compat_map_reply_t;

/** Opcode for xcb_xkb_set_compat_map. */
#define XCB_XKB_SET_COMPAT_MAP 11

/**
 * @brief xcb_xkb_set_compat_map_request_t
 **/
typedef struct xcb_xkb_set_compat_map_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint8_t               pad0;
    uint8_t               recomputeActions;
    uint8_t               truncateSI;
    uint8_t               groups;
    uint16_t              firstSI;
    uint16_t              nSI;
    uint8_t               pad1[2];
} xcb_xkb_set_compat_map_request_t;

/**
 * @brief xcb_xkb_get_indicator_state_cookie_t
 **/
typedef struct xcb_xkb_get_indicator_state_cookie_t {
    unsigned int sequence;
} xcb_xkb_get_indicator_state_cookie_t;

/** Opcode for xcb_xkb_get_indicator_state. */
#define XCB_XKB_GET_INDICATOR_STATE 12

/**
 * @brief xcb_xkb_get_indicator_state_request_t
 **/
typedef struct xcb_xkb_get_indicator_state_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint8_t               pad0[2];
} xcb_xkb_get_indicator_state_request_t;

/**
 * @brief xcb_xkb_get_indicator_state_reply_t
 **/
typedef struct xcb_xkb_get_indicator_state_reply_t {
    uint8_t  response_type;
    uint8_t  deviceID;
    uint16_t sequence;
    uint32_t length;
    uint32_t state;
    uint8_t  pad0[20];
} xcb_xkb_get_indicator_state_reply_t;

/**
 * @brief xcb_xkb_get_indicator_map_cookie_t
 **/
typedef struct xcb_xkb_get_indicator_map_cookie_t {
    unsigned int sequence;
} xcb_xkb_get_indicator_map_cookie_t;

/** Opcode for xcb_xkb_get_indicator_map. */
#define XCB_XKB_GET_INDICATOR_MAP 13

/**
 * @brief xcb_xkb_get_indicator_map_request_t
 **/
typedef struct xcb_xkb_get_indicator_map_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint8_t               pad0[2];
    uint32_t              which;
} xcb_xkb_get_indicator_map_request_t;

/**
 * @brief xcb_xkb_get_indicator_map_reply_t
 **/
typedef struct xcb_xkb_get_indicator_map_reply_t {
    uint8_t  response_type;
    uint8_t  deviceID;
    uint16_t sequence;
    uint32_t length;
    uint32_t which;
    uint32_t realIndicators;
    uint8_t  nIndicators;
    uint8_t  pad0[15];
} xcb_xkb_get_indicator_map_reply_t;

/** Opcode for xcb_xkb_set_indicator_map. */
#define XCB_XKB_SET_INDICATOR_MAP 14

/**
 * @brief xcb_xkb_set_indicator_map_request_t
 **/
typedef struct xcb_xkb_set_indicator_map_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint8_t               pad0[2];
    uint32_t              which;
} xcb_xkb_set_indicator_map_request_t;

/**
 * @brief xcb_xkb_get_named_indicator_cookie_t
 **/
typedef struct xcb_xkb_get_named_indicator_cookie_t {
    unsigned int sequence;
} xcb_xkb_get_named_indicator_cookie_t;

/** Opcode for xcb_xkb_get_named_indicator. */
#define XCB_XKB_GET_NAMED_INDICATOR 15

/**
 * @brief xcb_xkb_get_named_indicator_request_t
 **/
typedef struct xcb_xkb_get_named_indicator_request_t {
    uint8_t                  major_opcode;
    uint8_t                  minor_opcode;
    uint16_t                 length;
    xcb_xkb_device_spec_t    deviceSpec;
    xcb_xkb_led_class_spec_t ledClass;
    xcb_xkb_id_spec_t        ledID;
    uint8_t                  pad0[2];
    xcb_atom_t               indicator;
} xcb_xkb_get_named_indicator_request_t;

/**
 * @brief xcb_xkb_get_named_indicator_reply_t
 **/
typedef struct xcb_xkb_get_named_indicator_reply_t {
    uint8_t    response_type;
    uint8_t    deviceID;
    uint16_t   sequence;
    uint32_t   length;
    xcb_atom_t indicator;
    uint8_t    found;
    uint8_t    on;
    uint8_t    realIndicator;
    uint8_t    ndx;
    uint8_t    map_flags;
    uint8_t    map_whichGroups;
    uint8_t    map_groups;
    uint8_t    map_whichMods;
    uint8_t    map_mods;
    uint8_t    map_realMods;
    uint16_t   map_vmod;
    uint32_t   map_ctrls;
    uint8_t    supported;
    uint8_t    pad0[3];
} xcb_xkb_get_named_indicator_reply_t;

/** Opcode for xcb_xkb_set_named_indicator. */
#define XCB_XKB_SET_NAMED_INDICATOR 16

/**
 * @brief xcb_xkb_set_named_indicator_request_t
 **/
typedef struct xcb_xkb_set_named_indicator_request_t {
    uint8_t                  major_opcode;
    uint8_t                  minor_opcode;
    uint16_t                 length;
    xcb_xkb_device_spec_t    deviceSpec;
    xcb_xkb_led_class_spec_t ledClass;
    xcb_xkb_id_spec_t        ledID;
    uint8_t                  pad0[2];
    xcb_atom_t               indicator;
    uint8_t                  setState;
    uint8_t                  on;
    uint8_t                  setMap;
    uint8_t                  createMap;
    uint8_t                  pad1;
    uint8_t                  map_flags;
    uint8_t                  map_whichGroups;
    uint8_t                  map_groups;
    uint8_t                  map_whichMods;
    uint8_t                  map_realMods;
    uint16_t                 map_vmods;
    uint32_t                 map_ctrls;
} xcb_xkb_set_named_indicator_request_t;

/**
 * @brief xcb_xkb_get_names_cookie_t
 **/
typedef struct xcb_xkb_get_names_cookie_t {
    unsigned int sequence;
} xcb_xkb_get_names_cookie_t;

/** Opcode for xcb_xkb_get_names. */
#define XCB_XKB_GET_NAMES 17

/**
 * @brief xcb_xkb_get_names_request_t
 **/
typedef struct xcb_xkb_get_names_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint8_t               pad0[2];
    uint32_t              which;
} xcb_xkb_get_names_request_t;

/**
 * @brief xcb_xkb_get_names_value_list_t
 **/
typedef struct xcb_xkb_get_names_value_list_t {
    xcb_atom_t           keycodesName;
    xcb_atom_t           geometryName;
    xcb_atom_t           symbolsName;
    xcb_atom_t           physSymbolsName;
    xcb_atom_t           typesName;
    xcb_atom_t           compatName;
    xcb_atom_t          *typeNames;
    uint8_t             *nLevelsPerType;
    uint8_t             *pad1;
    xcb_atom_t          *ktLevelNames;
    xcb_atom_t          *indicatorNames;
    xcb_atom_t          *virtualModNames;
    xcb_atom_t          *groups;
    xcb_xkb_key_name_t  *keyNames;
    xcb_xkb_key_alias_t *keyAliases;
    xcb_atom_t          *radioGroupNames;
} xcb_xkb_get_names_value_list_t;

/**
 * @brief xcb_xkb_get_names_reply_t
 **/
typedef struct xcb_xkb_get_names_reply_t {
    uint8_t       response_type;
    uint8_t       deviceID;
    uint16_t      sequence;
    uint32_t      length;
    uint32_t      which;
    xcb_keycode_t minKeyCode;
    xcb_keycode_t maxKeyCode;
    uint8_t       nTypes;
    uint8_t       groupNames;
    uint16_t      virtualMods;
    xcb_keycode_t firstKey;
    uint8_t       nKeys;
    uint32_t      indicators;
    uint8_t       nRadioGroups;
    uint8_t       nKeyAliases;
    uint16_t      nKTLevels;
    uint8_t       pad0[4];
} xcb_xkb_get_names_reply_t;

/**
 * @brief xcb_xkb_set_names_values_t
 **/
typedef struct xcb_xkb_set_names_values_t {
    xcb_atom_t           keycodesName;
    xcb_atom_t           geometryName;
    xcb_atom_t           symbolsName;
    xcb_atom_t           physSymbolsName;
    xcb_atom_t           typesName;
    xcb_atom_t           compatName;
    xcb_atom_t          *typeNames;
    uint8_t             *nLevelsPerType;
    xcb_atom_t          *ktLevelNames;
    xcb_atom_t          *indicatorNames;
    xcb_atom_t          *virtualModNames;
    xcb_atom_t          *groups;
    xcb_xkb_key_name_t  *keyNames;
    xcb_xkb_key_alias_t *keyAliases;
    xcb_atom_t          *radioGroupNames;
} xcb_xkb_set_names_values_t;

/** Opcode for xcb_xkb_set_names. */
#define XCB_XKB_SET_NAMES 18

/**
 * @brief xcb_xkb_set_names_request_t
 **/
typedef struct xcb_xkb_set_names_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint16_t              virtualMods;
    uint32_t              which;
    uint8_t               firstType;
    uint8_t               nTypes;
    uint8_t               firstKTLevelt;
    uint8_t               nKTLevels;
    uint32_t              indicators;
    uint8_t               groupNames;
    uint8_t               nRadioGroups;
    xcb_keycode_t         firstKey;
    uint8_t               nKeys;
    uint8_t               nKeyAliases;
    uint8_t               pad0;
    uint16_t              totalKTLevelNames;
} xcb_xkb_set_names_request_t;

/**
 * @brief xcb_xkb_per_client_flags_cookie_t
 **/
typedef struct xcb_xkb_per_client_flags_cookie_t {
    unsigned int sequence;
} xcb_xkb_per_client_flags_cookie_t;

/** Opcode for xcb_xkb_per_client_flags. */
#define XCB_XKB_PER_CLIENT_FLAGS 21

/**
 * @brief xcb_xkb_per_client_flags_request_t
 **/
typedef struct xcb_xkb_per_client_flags_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint8_t               pad0[2];
    uint32_t              change;
    uint32_t              value;
    uint32_t              ctrlsToChange;
    uint32_t              autoCtrls;
    uint32_t              autoCtrlsValues;
} xcb_xkb_per_client_flags_request_t;

/**
 * @brief xcb_xkb_per_client_flags_reply_t
 **/
typedef struct xcb_xkb_per_client_flags_reply_t {
    uint8_t  response_type;
    uint8_t  deviceID;
    uint16_t sequence;
    uint32_t length;
    uint32_t supported;
    uint32_t value;
    uint32_t autoCtrls;
    uint32_t autoCtrlsValues;
    uint8_t  pad0[8];
} xcb_xkb_per_client_flags_reply_t;

/**
 * @brief xcb_xkb_list_components_cookie_t
 **/
typedef struct xcb_xkb_list_components_cookie_t {
    unsigned int sequence;
} xcb_xkb_list_components_cookie_t;

/** Opcode for xcb_xkb_list_components. */
#define XCB_XKB_LIST_COMPONENTS 22

/**
 * @brief xcb_xkb_list_components_request_t
 **/
typedef struct xcb_xkb_list_components_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint16_t              maxNames;
} xcb_xkb_list_components_request_t;

/**
 * @brief xcb_xkb_list_components_reply_t
 **/
typedef struct xcb_xkb_list_components_reply_t {
    uint8_t  response_type;
    uint8_t  deviceID;
    uint16_t sequence;
    uint32_t length;
    uint16_t nKeymaps;
    uint16_t nKeycodes;
    uint16_t nTypes;
    uint16_t nCompatMaps;
    uint16_t nSymbols;
    uint16_t nGeometries;
    uint16_t extra;
    uint8_t  pad0[10];
} xcb_xkb_list_components_reply_t;

/**
 * @brief xcb_xkb_get_kbd_by_name_cookie_t
 **/
typedef struct xcb_xkb_get_kbd_by_name_cookie_t {
    unsigned int sequence;
} xcb_xkb_get_kbd_by_name_cookie_t;

/** Opcode for xcb_xkb_get_kbd_by_name. */
#define XCB_XKB_GET_KBD_BY_NAME 23

/**
 * @brief xcb_xkb_get_kbd_by_name_request_t
 **/
typedef struct xcb_xkb_get_kbd_by_name_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint16_t              need;
    uint16_t              want;
    uint8_t               load;
    uint8_t               pad0;
} xcb_xkb_get_kbd_by_name_request_t;

/**
 * @brief xcb_xkb_get_kbd_by_name_replies_types_map_t
 **/
typedef struct xcb_xkb_get_kbd_by_name_replies_types_map_t {
    xcb_xkb_key_type_t      *types_rtrn;
    xcb_xkb_key_sym_map_t   *syms_rtrn;
    uint8_t                 *acts_rtrn_count;
    xcb_xkb_action_t        *acts_rtrn_acts;
    xcb_xkb_set_behavior_t  *behaviors_rtrn;
    uint8_t                 *vmods_rtrn;
    xcb_xkb_set_explicit_t  *explicit_rtrn;
    xcb_xkb_key_mod_map_t   *modmap_rtrn;
    xcb_xkb_key_v_mod_map_t *vmodmap_rtrn;
} xcb_xkb_get_kbd_by_name_replies_types_map_t;

/**
 * @brief xcb_xkb_get_kbd_by_name_replies_key_names_value_list_t
 **/
typedef struct xcb_xkb_get_kbd_by_name_replies_key_names_value_list_t {
    xcb_atom_t           keycodesName;
    xcb_atom_t           geometryName;
    xcb_atom_t           symbolsName;
    xcb_atom_t           physSymbolsName;
    xcb_atom_t           typesName;
    xcb_atom_t           compatName;
    xcb_atom_t          *typeNames;
    uint8_t             *nLevelsPerType;
    xcb_atom_t          *ktLevelNames;
    xcb_atom_t          *indicatorNames;
    xcb_atom_t          *virtualModNames;
    xcb_atom_t          *groups;
    xcb_xkb_key_name_t  *keyNames;
    xcb_xkb_key_alias_t *keyAliases;
    xcb_atom_t          *radioGroupNames;
} xcb_xkb_get_kbd_by_name_replies_key_names_value_list_t;

/**
 * @brief xcb_xkb_get_kbd_by_name_replies_t
 **/
typedef struct xcb_xkb_get_kbd_by_name_replies_t {
    struct {
        uint8_t                                                 getmap_type;
        uint8_t                                                 typeDeviceID;
        uint16_t                                                getmap_sequence;
        uint32_t                                                getmap_length;
        uint8_t                                                 pad1[2];
        xcb_keycode_t                                           typeMinKeyCode;
        xcb_keycode_t                                           typeMaxKeyCode;
        uint16_t                                                present;
        uint8_t                                                 firstType;
        uint8_t                                                 nTypes;
        uint8_t                                                 totalTypes;
        xcb_keycode_t                                           firstKeySym;
        uint16_t                                                totalSyms;
        uint8_t                                                 nKeySyms;
        xcb_keycode_t                                           firstKeyAction;
        uint16_t                                                totalActions;
        uint8_t                                                 nKeyActions;
        xcb_keycode_t                                           firstKeyBehavior;
        uint8_t                                                 nKeyBehaviors;
        uint8_t                                                 totalKeyBehaviors;
        xcb_keycode_t                                           firstKeyExplicit;
        uint8_t                                                 nKeyExplicit;
        uint8_t                                                 totalKeyExplicit;
        xcb_keycode_t                                           firstModMapKey;
        uint8_t                                                 nModMapKeys;
        uint8_t                                                 totalModMapKeys;
        xcb_keycode_t                                           firstVModMapKey;
        uint8_t                                                 nVModMapKeys;
        uint8_t                                                 totalVModMapKeys;
        uint8_t                                                 pad2;
        uint16_t                                                virtualMods;
        xcb_xkb_get_kbd_by_name_replies_types_map_t             map;
    } types;
    struct {
        uint8_t                                                 compatmap_type;
        uint8_t                                                 compatDeviceID;
        uint16_t                                                compatmap_sequence;
        uint32_t                                                compatmap_length;
        uint8_t                                                 groupsRtrn;
        uint8_t                                                 pad7;
        uint16_t                                                firstSIRtrn;
        uint16_t                                                nSIRtrn;
        uint16_t                                                nTotalSI;
        uint8_t                                                 pad8[16];
        xcb_xkb_sym_interpret_t                                *si_rtrn;
        xcb_xkb_mod_def_t                                      *group_rtrn;
    } compat_map;
    struct {
        uint8_t                                                 indicatormap_type;
        uint8_t                                                 indicatorDeviceID;
        uint16_t                                                indicatormap_sequence;
        uint32_t                                                indicatormap_length;
        uint32_t                                                which;
        uint32_t                                                realIndicators;
        uint8_t                                                 nIndicators;
        uint8_t                                                 pad9[15];
        xcb_xkb_indicator_map_t                                *maps;
    } indicator_maps;
    struct {
        uint8_t                                                 keyname_type;
        uint8_t                                                 keyDeviceID;
        uint16_t                                                keyname_sequence;
        uint32_t                                                keyname_length;
        uint32_t                                                which;
        xcb_keycode_t                                           keyMinKeyCode;
        xcb_keycode_t                                           keyMaxKeyCode;
        uint8_t                                                 nTypes;
        uint8_t                                                 groupNames;
        uint16_t                                                virtualMods;
        xcb_keycode_t                                           firstKey;
        uint8_t                                                 nKeys;
        uint32_t                                                indicators;
        uint8_t                                                 nRadioGroups;
        uint8_t                                                 nKeyAliases;
        uint16_t                                                nKTLevels;
        uint8_t                                                 pad10[4];
        xcb_xkb_get_kbd_by_name_replies_key_names_value_list_t  valueList;
    } key_names;
    struct {
        uint8_t                                                 geometry_type;
        uint8_t                                                 geometryDeviceID;
        uint16_t                                                geometry_sequence;
        uint32_t                                                geometry_length;
        xcb_atom_t                                              name;
        uint8_t                                                 geometryFound;
        uint8_t                                                 pad12;
        uint16_t                                                widthMM;
        uint16_t                                                heightMM;
        uint16_t                                                nProperties;
        uint16_t                                                nColors;
        uint16_t                                                nShapes;
        uint16_t                                                nSections;
        uint16_t                                                nDoodads;
        uint16_t                                                nKeyAliases;
        uint8_t                                                 baseColorNdx;
        uint8_t                                                 labelColorNdx;
        xcb_xkb_counted_string_16_t                            *labelFont;
    } geometry;
} xcb_xkb_get_kbd_by_name_replies_t;

xcb_xkb_get_kbd_by_name_replies_types_map_t *
xcb_xkb_get_kbd_by_name_replies_types_map (const xcb_xkb_get_kbd_by_name_replies_t *R);

/**
 * @brief xcb_xkb_get_kbd_by_name_reply_t
 **/
typedef struct xcb_xkb_get_kbd_by_name_reply_t {
    uint8_t       response_type;
    uint8_t       deviceID;
    uint16_t      sequence;
    uint32_t      length;
    xcb_keycode_t minKeyCode;
    xcb_keycode_t maxKeyCode;
    uint8_t       loaded;
    uint8_t       newKeyboard;
    uint16_t      found;
    uint16_t      reported;
    uint8_t       pad0[16];
} xcb_xkb_get_kbd_by_name_reply_t;

/**
 * @brief xcb_xkb_get_device_info_cookie_t
 **/
typedef struct xcb_xkb_get_device_info_cookie_t {
    unsigned int sequence;
} xcb_xkb_get_device_info_cookie_t;

/** Opcode for xcb_xkb_get_device_info. */
#define XCB_XKB_GET_DEVICE_INFO 24

/**
 * @brief xcb_xkb_get_device_info_request_t
 **/
typedef struct xcb_xkb_get_device_info_request_t {
    uint8_t                  major_opcode;
    uint8_t                  minor_opcode;
    uint16_t                 length;
    xcb_xkb_device_spec_t    deviceSpec;
    uint16_t                 wanted;
    uint8_t                  allButtons;
    uint8_t                  firstButton;
    uint8_t                  nButtons;
    uint8_t                  pad0;
    xcb_xkb_led_class_spec_t ledClass;
    xcb_xkb_id_spec_t        ledID;
} xcb_xkb_get_device_info_request_t;

/**
 * @brief xcb_xkb_get_device_info_reply_t
 **/
typedef struct xcb_xkb_get_device_info_reply_t {
    uint8_t    response_type;
    uint8_t    deviceID;
    uint16_t   sequence;
    uint32_t   length;
    uint16_t   present;
    uint16_t   supported;
    uint16_t   unsupported;
    uint16_t   nDeviceLedFBs;
    uint8_t    firstBtnWanted;
    uint8_t    nBtnsWanted;
    uint8_t    firstBtnRtrn;
    uint8_t    nBtnsRtrn;
    uint8_t    totalBtns;
    uint8_t    hasOwnState;
    uint16_t   dfltKbdFB;
    uint16_t   dfltLedFB;
    uint8_t    pad0[2];
    xcb_atom_t devType;
    uint16_t   nameLen;
} xcb_xkb_get_device_info_reply_t;

/** Opcode for xcb_xkb_set_device_info. */
#define XCB_XKB_SET_DEVICE_INFO 25

/**
 * @brief xcb_xkb_set_device_info_request_t
 **/
typedef struct xcb_xkb_set_device_info_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xkb_device_spec_t deviceSpec;
    uint8_t               firstBtn;
    uint8_t               nBtns;
    uint16_t              change;
    uint16_t              nDeviceLedFBs;
} xcb_xkb_set_device_info_request_t;

/**
 * @brief xcb_xkb_set_debugging_flags_cookie_t
 **/
typedef struct xcb_xkb_set_debugging_flags_cookie_t {
    unsigned int sequence;
} xcb_xkb_set_debugging_flags_cookie_t;

/** Opcode for xcb_xkb_set_debugging_flags. */
#define XCB_XKB_SET_DEBUGGING_FLAGS 101

/**
 * @brief xcb_xkb_set_debugging_flags_request_t
 **/
typedef struct xcb_xkb_set_debugging_flags_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint16_t msgLength;
    uint8_t  pad0[2];
    uint32_t affectFlags;
    uint32_t flags;
    uint32_t affectCtrls;
    uint32_t ctrls;
} xcb_xkb_set_debugging_flags_request_t;

/**
 * @brief xcb_xkb_set_debugging_flags_reply_t
 **/
typedef struct xcb_xkb_set_debugging_flags_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t currentFlags;
    uint32_t currentCtrls;
    uint32_t supportedFlags;
    uint32_t supportedCtrls;
    uint8_t  pad1[8];
} xcb_xkb_set_debugging_flags_reply_t;

/** Opcode for xcb_xkb_new_keyboard_notify. */
#define XCB_XKB_NEW_KEYBOARD_NOTIFY 0

/**
 * @brief xcb_xkb_new_keyboard_notify_event_t
 **/
typedef struct xcb_xkb_new_keyboard_notify_event_t {
    uint8_t         response_type;
    uint8_t         xkbType;
    uint16_t        sequence;
    xcb_timestamp_t time;
    uint8_t         deviceID;
    uint8_t         oldDeviceID;
    xcb_keycode_t   minKeyCode;
    xcb_keycode_t   maxKeyCode;
    xcb_keycode_t   oldMinKeyCode;
    xcb_keycode_t   oldMaxKeyCode;
    uint8_t         requestMajor;
    uint8_t         requestMinor;
    uint16_t        changed;
    uint8_t         pad0[14];
} xcb_xkb_new_keyboard_notify_event_t;

/** Opcode for xcb_xkb_map_notify. */
#define XCB_XKB_MAP_NOTIFY 1

/**
 * @brief xcb_xkb_map_notify_event_t
 **/
typedef struct xcb_xkb_map_notify_event_t {
    uint8_t         response_type;
    uint8_t         xkbType;
    uint16_t        sequence;
    xcb_timestamp_t time;
    uint8_t         deviceID;
    uint8_t         ptrBtnActions;
    uint16_t        changed;
    xcb_keycode_t   minKeyCode;
    xcb_keycode_t   maxKeyCode;
    uint8_t         firstType;
    uint8_t         nTypes;
    xcb_keycode_t   firstKeySym;
    uint8_t         nKeySyms;
    xcb_keycode_t   firstKeyAct;
    uint8_t         nKeyActs;
    xcb_keycode_t   firstKeyBehavior;
    uint8_t         nKeyBehavior;
    xcb_keycode_t   firstKeyExplicit;
    uint8_t         nKeyExplicit;
    xcb_keycode_t   firstModMapKey;
    uint8_t         nModMapKeys;
    xcb_keycode_t   firstVModMapKey;
    uint8_t         nVModMapKeys;
    uint16_t        virtualMods;
    uint8_t         pad0[2];
} xcb_xkb_map_notify_event_t;

/** Opcode for xcb_xkb_state_notify. */
#define XCB_XKB_STATE_NOTIFY 2

/**
 * @brief xcb_xkb_state_notify_event_t
 **/
typedef struct xcb_xkb_state_notify_event_t {
    uint8_t         response_type;
    uint8_t         xkbType;
    uint16_t        sequence;
    xcb_timestamp_t time;
    uint8_t         deviceID;
    uint8_t         mods;
    uint8_t         baseMods;
    uint8_t         latchedMods;
    uint8_t         lockedMods;
    uint8_t         group;
    int16_t         baseGroup;
    int16_t         latchedGroup;
    uint8_t         lockedGroup;
    uint8_t         compatState;
    uint8_t         grabMods;
    uint8_t         compatGrabMods;
    uint8_t         lookupMods;
    uint8_t         compatLoockupMods;
    uint16_t        ptrBtnState;
    uint16_t        changed;
    xcb_keycode_t   keycode;
    uint8_t         eventType;
    uint8_t         requestMajor;
    uint8_t         requestMinor;
} xcb_xkb_state_notify_event_t;

/** Opcode for xcb_xkb_controls_notify. */
#define XCB_XKB_CONTROLS_NOTIFY 3

/**
 * @brief xcb_xkb_controls_notify_event_t
 **/
typedef struct xcb_xkb_controls_notify_event_t {
    uint8_t         response_type;
    uint8_t         xkbType;
    uint16_t        sequence;
    xcb_timestamp_t time;
    uint8_t         deviceID;
    uint8_t         numGroups;
    uint8_t         pad0[2];
    uint32_t        changedControls;
    uint32_t        enabledControls;
    uint32_t        enabledControlChanges;
    xcb_keycode_t   keycode;
    uint8_t         eventType;
    uint8_t         requestMajor;
    uint8_t         requestMinor;
    uint8_t         pad1[4];
} xcb_xkb_controls_notify_event_t;

/** Opcode for xcb_xkb_indicator_state_notify. */
#define XCB_XKB_INDICATOR_STATE_NOTIFY 4

/**
 * @brief xcb_xkb_indicator_state_notify_event_t
 **/
typedef struct xcb_xkb_indicator_state_notify_event_t {
    uint8_t         response_type;
    uint8_t         xkbType;
    uint16_t        sequence;
    xcb_timestamp_t time;
    uint8_t         deviceID;
    uint8_t         pad0[3];
    uint32_t        state;
    uint32_t        stateChanged;
    uint8_t         pad1[12];
} xcb_xkb_indicator_state_notify_event_t;

/** Opcode for xcb_xkb_indicator_map_notify. */
#define XCB_XKB_INDICATOR_MAP_NOTIFY 5

/**
 * @brief xcb_xkb_indicator_map_notify_event_t
 **/
typedef struct xcb_xkb_indicator_map_notify_event_t {
    uint8_t         response_type;
    uint8_t         xkbType;
    uint16_t        sequence;
    xcb_timestamp_t time;
    uint8_t         deviceID;
    uint8_t         pad0[3];
    uint32_t        state;
    uint32_t        mapChanged;
    uint8_t         pad1[12];
} xcb_xkb_indicator_map_notify_event_t;

/** Opcode for xcb_xkb_names_notify. */
#define XCB_XKB_NAMES_NOTIFY 6

/**
 * @brief xcb_xkb_names_notify_event_t
 **/
typedef struct xcb_xkb_names_notify_event_t {
    uint8_t         response_type;
    uint8_t         xkbType;
    uint16_t        sequence;
    xcb_timestamp_t time;
    uint8_t         deviceID;
    uint8_t         pad0;
    uint16_t        changed;
    uint8_t         firstType;
    uint8_t         nTypes;
    uint8_t         firstLevelName;
    uint8_t         nLevelNames;
    uint8_t         pad1;
    uint8_t         nRadioGroups;
    uint8_t         nKeyAliases;
    uint8_t         changedGroupNames;
    uint16_t        changedVirtualMods;
    xcb_keycode_t   firstKey;
    uint8_t         nKeys;
    uint32_t        changedIndicators;
    uint8_t         pad2[4];
} xcb_xkb_names_notify_event_t;

/** Opcode for xcb_xkb_compat_map_notify. */
#define XCB_XKB_COMPAT_MAP_NOTIFY 7

/**
 * @brief xcb_xkb_compat_map_notify_event_t
 **/
typedef struct xcb_xkb_compat_map_notify_event_t {
    uint8_t         response_type;
    uint8_t         xkbType;
    uint16_t        sequence;
    xcb_timestamp_t time;
    uint8_t         deviceID;
    uint8_t         changedGroups;
    uint16_t        firstSI;
    uint16_t        nSI;
    uint16_t        nTotalSI;
    uint8_t         pad0[16];
} xcb_xkb_compat_map_notify_event_t;

/** Opcode for xcb_xkb_bell_notify. */
#define XCB_XKB_BELL_NOTIFY 8

/**
 * @brief xcb_xkb_bell_notify_event_t
 **/
typedef struct xcb_xkb_bell_notify_event_t {
    uint8_t         response_type;
    uint8_t         xkbType;
    uint16_t        sequence;
    xcb_timestamp_t time;
    uint8_t         deviceID;
    uint8_t         bellClass;
    uint8_t         bellID;
    uint8_t         percent;
    uint16_t        pitch;
    uint16_t        duration;
    xcb_atom_t      name;
    xcb_window_t    window;
    uint8_t         eventOnly;
    uint8_t         pad0[7];
} xcb_xkb_bell_notify_event_t;

/** Opcode for xcb_xkb_action_message. */
#define XCB_XKB_ACTION_MESSAGE 9

/**
 * @brief xcb_xkb_action_message_event_t
 **/
typedef struct xcb_xkb_action_message_event_t {
    uint8_t           response_type;
    uint8_t           xkbType;
    uint16_t          sequence;
    xcb_timestamp_t   time;
    uint8_t           deviceID;
    xcb_keycode_t     keycode;
    uint8_t           press;
    uint8_t           keyEventFollows;
    uint8_t           mods;
    uint8_t           group;
    xcb_xkb_string8_t message[8];
    uint8_t           pad0[10];
} xcb_xkb_action_message_event_t;

/** Opcode for xcb_xkb_access_x_notify. */
#define XCB_XKB_ACCESS_X_NOTIFY 10

/**
 * @brief xcb_xkb_access_x_notify_event_t
 **/
typedef struct xcb_xkb_access_x_notify_event_t {
    uint8_t         response_type;
    uint8_t         xkbType;
    uint16_t        sequence;
    xcb_timestamp_t time;
    uint8_t         deviceID;
    xcb_keycode_t   keycode;
    uint16_t        detailt;
    uint16_t        slowKeysDelay;
    uint16_t        debounceDelay;
    uint8_t         pad0[16];
} xcb_xkb_access_x_notify_event_t;

/** Opcode for xcb_xkb_extension_device_notify. */
#define XCB_XKB_EXTENSION_DEVICE_NOTIFY 11

/**
 * @brief xcb_xkb_extension_device_notify_event_t
 **/
typedef struct xcb_xkb_extension_device_notify_event_t {
    uint8_t         response_type;
    uint8_t         xkbType;
    uint16_t        sequence;
    xcb_timestamp_t time;
    uint8_t         deviceID;
    uint8_t         pad0;
    uint16_t        reason;
    uint16_t        ledClass;
    uint16_t        ledID;
    uint32_t        ledsDefined;
    uint32_t        ledState;
    uint8_t         firstButton;
    uint8_t         nButtons;
    uint16_t        supported;
    uint16_t        unsupported;
    uint8_t         pad1[2];
} xcb_xkb_extension_device_notify_event_t;

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_device_spec_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_device_spec_t)
 */
void
xcb_xkb_device_spec_next (xcb_xkb_device_spec_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_device_spec_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_device_spec_end (xcb_xkb_device_spec_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_led_class_spec_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_led_class_spec_t)
 */
void
xcb_xkb_led_class_spec_next (xcb_xkb_led_class_spec_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_led_class_spec_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_led_class_spec_end (xcb_xkb_led_class_spec_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_bell_class_spec_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_bell_class_spec_t)
 */
void
xcb_xkb_bell_class_spec_next (xcb_xkb_bell_class_spec_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_bell_class_spec_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_bell_class_spec_end (xcb_xkb_bell_class_spec_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_id_spec_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_id_spec_t)
 */
void
xcb_xkb_id_spec_next (xcb_xkb_id_spec_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_id_spec_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_id_spec_end (xcb_xkb_id_spec_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_indicator_map_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_indicator_map_t)
 */
void
xcb_xkb_indicator_map_next (xcb_xkb_indicator_map_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_indicator_map_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_indicator_map_end (xcb_xkb_indicator_map_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_mod_def_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_mod_def_t)
 */
void
xcb_xkb_mod_def_next (xcb_xkb_mod_def_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_mod_def_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_mod_def_end (xcb_xkb_mod_def_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_key_name_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_key_name_t)
 */
void
xcb_xkb_key_name_next (xcb_xkb_key_name_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_key_name_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_key_name_end (xcb_xkb_key_name_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_key_alias_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_key_alias_t)
 */
void
xcb_xkb_key_alias_next (xcb_xkb_key_alias_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_key_alias_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_key_alias_end (xcb_xkb_key_alias_iterator_t i);

int
xcb_xkb_counted_string_16_sizeof (const void  *_buffer);

char *
xcb_xkb_counted_string_16_string (const xcb_xkb_counted_string_16_t *R);

int
xcb_xkb_counted_string_16_string_length (const xcb_xkb_counted_string_16_t *R);

xcb_generic_iterator_t
xcb_xkb_counted_string_16_string_end (const xcb_xkb_counted_string_16_t *R);

void *
xcb_xkb_counted_string_16_alignment_pad (const xcb_xkb_counted_string_16_t *R);

int
xcb_xkb_counted_string_16_alignment_pad_length (const xcb_xkb_counted_string_16_t *R);

xcb_generic_iterator_t
xcb_xkb_counted_string_16_alignment_pad_end (const xcb_xkb_counted_string_16_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_counted_string_16_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_counted_string_16_t)
 */
void
xcb_xkb_counted_string_16_next (xcb_xkb_counted_string_16_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_counted_string_16_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_counted_string_16_end (xcb_xkb_counted_string_16_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_kt_map_entry_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_kt_map_entry_t)
 */
void
xcb_xkb_kt_map_entry_next (xcb_xkb_kt_map_entry_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_kt_map_entry_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_kt_map_entry_end (xcb_xkb_kt_map_entry_iterator_t i);

int
xcb_xkb_key_type_sizeof (const void  *_buffer);

xcb_xkb_kt_map_entry_t *
xcb_xkb_key_type_map (const xcb_xkb_key_type_t *R);

int
xcb_xkb_key_type_map_length (const xcb_xkb_key_type_t *R);

xcb_xkb_kt_map_entry_iterator_t
xcb_xkb_key_type_map_iterator (const xcb_xkb_key_type_t *R);

xcb_xkb_mod_def_t *
xcb_xkb_key_type_preserve (const xcb_xkb_key_type_t *R);

int
xcb_xkb_key_type_preserve_length (const xcb_xkb_key_type_t *R);

xcb_xkb_mod_def_iterator_t
xcb_xkb_key_type_preserve_iterator (const xcb_xkb_key_type_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_key_type_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_key_type_t)
 */
void
xcb_xkb_key_type_next (xcb_xkb_key_type_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_key_type_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_key_type_end (xcb_xkb_key_type_iterator_t i);

int
xcb_xkb_key_sym_map_sizeof (const void  *_buffer);

xcb_keysym_t *
xcb_xkb_key_sym_map_syms (const xcb_xkb_key_sym_map_t *R);

int
xcb_xkb_key_sym_map_syms_length (const xcb_xkb_key_sym_map_t *R);

xcb_generic_iterator_t
xcb_xkb_key_sym_map_syms_end (const xcb_xkb_key_sym_map_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_key_sym_map_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_key_sym_map_t)
 */
void
xcb_xkb_key_sym_map_next (xcb_xkb_key_sym_map_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_key_sym_map_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_key_sym_map_end (xcb_xkb_key_sym_map_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_common_behavior_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_common_behavior_t)
 */
void
xcb_xkb_common_behavior_next (xcb_xkb_common_behavior_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_common_behavior_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_common_behavior_end (xcb_xkb_common_behavior_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_default_behavior_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_default_behavior_t)
 */
void
xcb_xkb_default_behavior_next (xcb_xkb_default_behavior_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_default_behavior_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_default_behavior_end (xcb_xkb_default_behavior_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_lock_behavior_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_lock_behavior_t)
 */
void
xcb_xkb_lock_behavior_next (xcb_xkb_lock_behavior_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_lock_behavior_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_lock_behavior_end (xcb_xkb_lock_behavior_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_radio_group_behavior_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_radio_group_behavior_t)
 */
void
xcb_xkb_radio_group_behavior_next (xcb_xkb_radio_group_behavior_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_radio_group_behavior_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_radio_group_behavior_end (xcb_xkb_radio_group_behavior_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_overlay_behavior_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_overlay_behavior_t)
 */
void
xcb_xkb_overlay_behavior_next (xcb_xkb_overlay_behavior_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_overlay_behavior_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_overlay_behavior_end (xcb_xkb_overlay_behavior_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_permament_lock_behavior_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_permament_lock_behavior_t)
 */
void
xcb_xkb_permament_lock_behavior_next (xcb_xkb_permament_lock_behavior_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_permament_lock_behavior_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_permament_lock_behavior_end (xcb_xkb_permament_lock_behavior_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_permament_radio_group_behavior_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_permament_radio_group_behavior_t)
 */
void
xcb_xkb_permament_radio_group_behavior_next (xcb_xkb_permament_radio_group_behavior_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_permament_radio_group_behavior_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_permament_radio_group_behavior_end (xcb_xkb_permament_radio_group_behavior_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_permament_overlay_behavior_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_permament_overlay_behavior_t)
 */
void
xcb_xkb_permament_overlay_behavior_next (xcb_xkb_permament_overlay_behavior_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_permament_overlay_behavior_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_permament_overlay_behavior_end (xcb_xkb_permament_overlay_behavior_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_behavior_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_behavior_t)
 */
void
xcb_xkb_behavior_next (xcb_xkb_behavior_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_behavior_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_behavior_end (xcb_xkb_behavior_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_set_behavior_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_set_behavior_t)
 */
void
xcb_xkb_set_behavior_next (xcb_xkb_set_behavior_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_set_behavior_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_set_behavior_end (xcb_xkb_set_behavior_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_set_explicit_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_set_explicit_t)
 */
void
xcb_xkb_set_explicit_next (xcb_xkb_set_explicit_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_set_explicit_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_set_explicit_end (xcb_xkb_set_explicit_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_key_mod_map_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_key_mod_map_t)
 */
void
xcb_xkb_key_mod_map_next (xcb_xkb_key_mod_map_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_key_mod_map_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_key_mod_map_end (xcb_xkb_key_mod_map_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_key_v_mod_map_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_key_v_mod_map_t)
 */
void
xcb_xkb_key_v_mod_map_next (xcb_xkb_key_v_mod_map_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_key_v_mod_map_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_key_v_mod_map_end (xcb_xkb_key_v_mod_map_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_kt_set_map_entry_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_kt_set_map_entry_t)
 */
void
xcb_xkb_kt_set_map_entry_next (xcb_xkb_kt_set_map_entry_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_kt_set_map_entry_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_kt_set_map_entry_end (xcb_xkb_kt_set_map_entry_iterator_t i);

int
xcb_xkb_set_key_type_sizeof (const void  *_buffer);

xcb_xkb_kt_set_map_entry_t *
xcb_xkb_set_key_type_entries (const xcb_xkb_set_key_type_t *R);

int
xcb_xkb_set_key_type_entries_length (const xcb_xkb_set_key_type_t *R);

xcb_xkb_kt_set_map_entry_iterator_t
xcb_xkb_set_key_type_entries_iterator (const xcb_xkb_set_key_type_t *R);

xcb_xkb_kt_set_map_entry_t *
xcb_xkb_set_key_type_preserve_entries (const xcb_xkb_set_key_type_t *R);

int
xcb_xkb_set_key_type_preserve_entries_length (const xcb_xkb_set_key_type_t *R);

xcb_xkb_kt_set_map_entry_iterator_t
xcb_xkb_set_key_type_preserve_entries_iterator (const xcb_xkb_set_key_type_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_set_key_type_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_set_key_type_t)
 */
void
xcb_xkb_set_key_type_next (xcb_xkb_set_key_type_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_set_key_type_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_set_key_type_end (xcb_xkb_set_key_type_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_string8_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_string8_t)
 */
void
xcb_xkb_string8_next (xcb_xkb_string8_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_string8_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_string8_end (xcb_xkb_string8_iterator_t i);

int
xcb_xkb_outline_sizeof (const void  *_buffer);

xcb_point_t *
xcb_xkb_outline_points (const xcb_xkb_outline_t *R);

int
xcb_xkb_outline_points_length (const xcb_xkb_outline_t *R);

xcb_point_iterator_t
xcb_xkb_outline_points_iterator (const xcb_xkb_outline_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_outline_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_outline_t)
 */
void
xcb_xkb_outline_next (xcb_xkb_outline_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_outline_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_outline_end (xcb_xkb_outline_iterator_t i);

int
xcb_xkb_shape_sizeof (const void  *_buffer);

int
xcb_xkb_shape_outlines_length (const xcb_xkb_shape_t *R);

xcb_xkb_outline_iterator_t
xcb_xkb_shape_outlines_iterator (const xcb_xkb_shape_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_shape_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_shape_t)
 */
void
xcb_xkb_shape_next (xcb_xkb_shape_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_shape_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_shape_end (xcb_xkb_shape_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_key_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_key_t)
 */
void
xcb_xkb_key_next (xcb_xkb_key_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_key_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_key_end (xcb_xkb_key_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_overlay_key_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_overlay_key_t)
 */
void
xcb_xkb_overlay_key_next (xcb_xkb_overlay_key_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_overlay_key_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_overlay_key_end (xcb_xkb_overlay_key_iterator_t i);

int
xcb_xkb_overlay_row_sizeof (const void  *_buffer);

xcb_xkb_overlay_key_t *
xcb_xkb_overlay_row_keys (const xcb_xkb_overlay_row_t *R);

int
xcb_xkb_overlay_row_keys_length (const xcb_xkb_overlay_row_t *R);

xcb_xkb_overlay_key_iterator_t
xcb_xkb_overlay_row_keys_iterator (const xcb_xkb_overlay_row_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_overlay_row_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_overlay_row_t)
 */
void
xcb_xkb_overlay_row_next (xcb_xkb_overlay_row_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_overlay_row_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_overlay_row_end (xcb_xkb_overlay_row_iterator_t i);

int
xcb_xkb_overlay_sizeof (const void  *_buffer);

int
xcb_xkb_overlay_rows_length (const xcb_xkb_overlay_t *R);

xcb_xkb_overlay_row_iterator_t
xcb_xkb_overlay_rows_iterator (const xcb_xkb_overlay_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_overlay_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_overlay_t)
 */
void
xcb_xkb_overlay_next (xcb_xkb_overlay_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_overlay_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_overlay_end (xcb_xkb_overlay_iterator_t i);

int
xcb_xkb_row_sizeof (const void  *_buffer);

xcb_xkb_key_t *
xcb_xkb_row_keys (const xcb_xkb_row_t *R);

int
xcb_xkb_row_keys_length (const xcb_xkb_row_t *R);

xcb_xkb_key_iterator_t
xcb_xkb_row_keys_iterator (const xcb_xkb_row_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_row_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_row_t)
 */
void
xcb_xkb_row_next (xcb_xkb_row_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_row_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_row_end (xcb_xkb_row_iterator_t i);

int
xcb_xkb_listing_sizeof (const void  *_buffer);

xcb_xkb_string8_t *
xcb_xkb_listing_string (const xcb_xkb_listing_t *R);

int
xcb_xkb_listing_string_length (const xcb_xkb_listing_t *R);

xcb_generic_iterator_t
xcb_xkb_listing_string_end (const xcb_xkb_listing_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_listing_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_listing_t)
 */
void
xcb_xkb_listing_next (xcb_xkb_listing_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_listing_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_listing_end (xcb_xkb_listing_iterator_t i);

int
xcb_xkb_device_led_info_sizeof (const void  *_buffer);

xcb_atom_t *
xcb_xkb_device_led_info_names (const xcb_xkb_device_led_info_t *R);

int
xcb_xkb_device_led_info_names_length (const xcb_xkb_device_led_info_t *R);

xcb_generic_iterator_t
xcb_xkb_device_led_info_names_end (const xcb_xkb_device_led_info_t *R);

xcb_xkb_indicator_map_t *
xcb_xkb_device_led_info_maps (const xcb_xkb_device_led_info_t *R);

int
xcb_xkb_device_led_info_maps_length (const xcb_xkb_device_led_info_t *R);

xcb_xkb_indicator_map_iterator_t
xcb_xkb_device_led_info_maps_iterator (const xcb_xkb_device_led_info_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_device_led_info_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_device_led_info_t)
 */
void
xcb_xkb_device_led_info_next (xcb_xkb_device_led_info_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_device_led_info_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_device_led_info_end (xcb_xkb_device_led_info_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_no_action_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_no_action_t)
 */
void
xcb_xkb_sa_no_action_next (xcb_xkb_sa_no_action_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_no_action_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_no_action_end (xcb_xkb_sa_no_action_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_set_mods_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_set_mods_t)
 */
void
xcb_xkb_sa_set_mods_next (xcb_xkb_sa_set_mods_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_set_mods_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_set_mods_end (xcb_xkb_sa_set_mods_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_latch_mods_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_latch_mods_t)
 */
void
xcb_xkb_sa_latch_mods_next (xcb_xkb_sa_latch_mods_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_latch_mods_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_latch_mods_end (xcb_xkb_sa_latch_mods_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_lock_mods_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_lock_mods_t)
 */
void
xcb_xkb_sa_lock_mods_next (xcb_xkb_sa_lock_mods_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_lock_mods_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_lock_mods_end (xcb_xkb_sa_lock_mods_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_set_group_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_set_group_t)
 */
void
xcb_xkb_sa_set_group_next (xcb_xkb_sa_set_group_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_set_group_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_set_group_end (xcb_xkb_sa_set_group_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_latch_group_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_latch_group_t)
 */
void
xcb_xkb_sa_latch_group_next (xcb_xkb_sa_latch_group_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_latch_group_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_latch_group_end (xcb_xkb_sa_latch_group_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_lock_group_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_lock_group_t)
 */
void
xcb_xkb_sa_lock_group_next (xcb_xkb_sa_lock_group_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_lock_group_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_lock_group_end (xcb_xkb_sa_lock_group_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_move_ptr_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_move_ptr_t)
 */
void
xcb_xkb_sa_move_ptr_next (xcb_xkb_sa_move_ptr_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_move_ptr_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_move_ptr_end (xcb_xkb_sa_move_ptr_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_ptr_btn_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_ptr_btn_t)
 */
void
xcb_xkb_sa_ptr_btn_next (xcb_xkb_sa_ptr_btn_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_ptr_btn_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_ptr_btn_end (xcb_xkb_sa_ptr_btn_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_lock_ptr_btn_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_lock_ptr_btn_t)
 */
void
xcb_xkb_sa_lock_ptr_btn_next (xcb_xkb_sa_lock_ptr_btn_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_lock_ptr_btn_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_lock_ptr_btn_end (xcb_xkb_sa_lock_ptr_btn_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_set_ptr_dflt_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_set_ptr_dflt_t)
 */
void
xcb_xkb_sa_set_ptr_dflt_next (xcb_xkb_sa_set_ptr_dflt_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_set_ptr_dflt_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_set_ptr_dflt_end (xcb_xkb_sa_set_ptr_dflt_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_iso_lock_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_iso_lock_t)
 */
void
xcb_xkb_sa_iso_lock_next (xcb_xkb_sa_iso_lock_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_iso_lock_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_iso_lock_end (xcb_xkb_sa_iso_lock_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_terminate_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_terminate_t)
 */
void
xcb_xkb_sa_terminate_next (xcb_xkb_sa_terminate_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_terminate_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_terminate_end (xcb_xkb_sa_terminate_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_switch_screen_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_switch_screen_t)
 */
void
xcb_xkb_sa_switch_screen_next (xcb_xkb_sa_switch_screen_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_switch_screen_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_switch_screen_end (xcb_xkb_sa_switch_screen_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_set_controls_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_set_controls_t)
 */
void
xcb_xkb_sa_set_controls_next (xcb_xkb_sa_set_controls_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_set_controls_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_set_controls_end (xcb_xkb_sa_set_controls_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_lock_controls_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_lock_controls_t)
 */
void
xcb_xkb_sa_lock_controls_next (xcb_xkb_sa_lock_controls_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_lock_controls_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_lock_controls_end (xcb_xkb_sa_lock_controls_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_action_message_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_action_message_t)
 */
void
xcb_xkb_sa_action_message_next (xcb_xkb_sa_action_message_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_action_message_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_action_message_end (xcb_xkb_sa_action_message_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_redirect_key_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_redirect_key_t)
 */
void
xcb_xkb_sa_redirect_key_next (xcb_xkb_sa_redirect_key_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_redirect_key_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_redirect_key_end (xcb_xkb_sa_redirect_key_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_device_btn_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_device_btn_t)
 */
void
xcb_xkb_sa_device_btn_next (xcb_xkb_sa_device_btn_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_device_btn_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_device_btn_end (xcb_xkb_sa_device_btn_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_lock_device_btn_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_lock_device_btn_t)
 */
void
xcb_xkb_sa_lock_device_btn_next (xcb_xkb_sa_lock_device_btn_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_lock_device_btn_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_lock_device_btn_end (xcb_xkb_sa_lock_device_btn_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sa_device_valuator_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sa_device_valuator_t)
 */
void
xcb_xkb_sa_device_valuator_next (xcb_xkb_sa_device_valuator_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sa_device_valuator_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sa_device_valuator_end (xcb_xkb_sa_device_valuator_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_si_action_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_si_action_t)
 */
void
xcb_xkb_si_action_next (xcb_xkb_si_action_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_si_action_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_si_action_end (xcb_xkb_si_action_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_sym_interpret_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_sym_interpret_t)
 */
void
xcb_xkb_sym_interpret_next (xcb_xkb_sym_interpret_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_sym_interpret_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_sym_interpret_end (xcb_xkb_sym_interpret_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xkb_action_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xkb_action_t)
 */
void
xcb_xkb_action_next (xcb_xkb_action_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xkb_action_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xkb_action_end (xcb_xkb_action_iterator_t i);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xkb_use_extension_cookie_t
xcb_xkb_use_extension (xcb_connection_t *c,
                       uint16_t          wantedMajor,
                       uint16_t          wantedMinor);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_xkb_use_extension_cookie_t
xcb_xkb_use_extension_unchecked (xcb_connection_t *c,
                                 uint16_t          wantedMajor,
                                 uint16_t          wantedMinor);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xkb_use_extension_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xkb_use_extension_reply_t *
xcb_xkb_use_extension_reply (xcb_connection_t                *c,
                             xcb_xkb_use_extension_cookie_t   cookie  /**< */,
                             xcb_generic_error_t            **e);

int
xcb_xkb_select_events_details_serialize (void                                  **_buffer,
                                         uint16_t                                affectWhich,
                                         uint16_t                                clear,
                                         uint16_t                                selectAll,
                                         const xcb_xkb_select_events_details_t  *_aux);

int
xcb_xkb_select_events_details_unpack (const void                       *_buffer,
                                      uint16_t                          affectWhich,
                                      uint16_t                          clear,
                                      uint16_t                          selectAll,
                                      xcb_xkb_select_events_details_t  *_aux);

int
xcb_xkb_select_events_details_sizeof (const void  *_buffer,
                                      uint16_t     affectWhich,
                                      uint16_t     clear,
                                      uint16_t     selectAll);

int
xcb_xkb_select_events_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_xkb_select_events_checked (xcb_connection_t      *c,
                               xcb_xkb_device_spec_t  deviceSpec,
                               uint16_t               affectWhich,
                               uint16_t               clear,
                               uint16_t               selectAll,
                               uint16_t               affectMap,
                               uint16_t               map,
                               const void            *details);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xkb_select_events (xcb_connection_t      *c,
                       xcb_xkb_device_spec_t  deviceSpec,
                       uint16_t               affectWhich,
                       uint16_t               clear,
                       uint16_t               selectAll,
                       uint16_t               affectMap,
                       uint16_t               map,
                       const void            *details);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_xkb_select_events_aux_checked (xcb_connection_t                      *c,
                                   xcb_xkb_device_spec_t                  deviceSpec,
                                   uint16_t                               affectWhich,
                                   uint16_t                               clear,
                                   uint16_t                               selectAll,
                                   uint16_t                               affectMap,
                                   uint16_t                               map,
                                   const xcb_xkb_select_events_details_t *details);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xkb_select_events_aux (xcb_connection_t                      *c,
                           xcb_xkb_device_spec_t                  deviceSpec,
                           uint16_t                               affectWhich,
                           uint16_t                               clear,
                           uint16_t                               selectAll,
                           uint16_t                               affectMap,
                           uint16_t                               map,
                           const xcb_xkb_select_events_details_t *details);

void *
xcb_xkb_select_events_details (const xcb_xkb_select_events_request_t *R);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_xkb_bell_checked (xcb_connection_t          *c,
                      xcb_xkb_device_spec_t      deviceSpec,
                      xcb_xkb_bell_class_spec_t  bellClass,
                      xcb_xkb_id_spec_t          bellID,
                      int8_t                     percent,
                      uint8_t                    forceSound,
                      uint8_t                    eventOnly,
                      int16_t                    pitch,
                      int16_t                    duration,
                      xcb_atom_t                 name,
                      xcb_window_t               window);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xkb_bell (xcb_connection_t          *c,
              xcb_xkb_device_spec_t      deviceSpec,
              xcb_xkb_bell_class_spec_t  bellClass,
              xcb_xkb_id_spec_t          bellID,
              int8_t                     percent,
              uint8_t                    forceSound,
              uint8_t                    eventOnly,
              int16_t                    pitch,
              int16_t                    duration,
              xcb_atom_t                 name,
              xcb_window_t               window);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xkb_get_state_cookie_t
xcb_xkb_get_state (xcb_connection_t      *c,
                   xcb_xkb_device_spec_t  deviceSpec);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_xkb_get_state_cookie_t
xcb_xkb_get_state_unchecked (xcb_connection_t      *c,
                             xcb_xkb_device_spec_t  deviceSpec);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xkb_get_state_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xkb_get_state_reply_t *
xcb_xkb_get_state_reply (xcb_connection_t            *c,
                         xcb_xkb_get_state_cookie_t   cookie  /**< */,
                         xcb_generic_error_t        **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_xkb_latch_lock_state_checked (xcb_connection_t      *c,
                                  xcb_xkb_device_spec_t  deviceSpec,
                                  uint8_t                affectModLocks,
                                  uint8_t                modLocks,
                                  uint8_t                lockGroup,
                                  uint8_t                groupLock,
                                  uint8_t                affectModLatches,
                                  uint8_t                latchGroup,
                                  uint16_t               groupLatch);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xkb_latch_lock_state (xcb_connection_t      *c,
                          xcb_xkb_device_spec_t  deviceSpec,
                          uint8_t                affectModLocks,
                          uint8_t                modLocks,
                          uint8_t                lockGroup,
                          uint8_t                groupLock,
                          uint8_t                affectModLatches,
                          uint8_t                latchGroup,
                          uint16_t               groupLatch);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xkb_get_controls_cookie_t
xcb_xkb_get_controls (xcb_connection_t      *c,
                      xcb_xkb_device_spec_t  deviceSpec);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_xkb_get_controls_cookie_t
xcb_xkb_get_controls_unchecked (xcb_connection_t      *c,
                                xcb_xkb_device_spec_t  deviceSpec);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xkb_get_controls_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xkb_get_controls_reply_t *
xcb_xkb_get_controls_reply (xcb_connection_t               *c,
                            xcb_xkb_get_controls_cookie_t   cookie  /**< */,
                            xcb_generic_error_t           **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_xkb_set_controls_checked (xcb_connection_t      *c,
                              xcb_xkb_device_spec_t  deviceSpec,
                              uint8_t                affectInternalRealMods,
                              uint8_t                internalRealMods,
                              uint8_t                affectIgnoreLockRealMods,
                              uint8_t                ignoreLockRealMods,
                              uint16_t               affectInternalVirtualMods,
                              uint16_t               internalVirtualMods,
                              uint16_t               affectIgnoreLockVirtualMods,
                              uint16_t               ignoreLockVirtualMods,
                              uint8_t                mouseKeysDfltBtn,
                              uint8_t                groupsWrap,
                              uint16_t               accessXOptions,
                              uint32_t               affectEnabledControls,
                              uint32_t               enabledControls,
                              uint32_t               changeControls,
                              uint16_t               repeatDelay,
                              uint16_t               repeatInterval,
                              uint16_t               slowKeysDelay,
                              uint16_t               debounceDelay,
                              uint16_t               mouseKeysDelay,
                              uint16_t               mouseKeysInterval,
                              uint16_t               mouseKeysTimeToMax,
                              uint16_t               mouseKeysMaxSpeed,
                              int16_t                mouseKeysCurve,
                              uint16_t               accessXTimeout,
                              uint32_t               accessXTimeoutMask,
                              uint32_t               accessXTimeoutValues,
                              uint16_t               accessXTimeoutOptionsMask,
                              uint16_t               accessXTimeoutOptionsValues,
                              const uint8_t         *perKeyRepeat);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xkb_set_controls (xcb_connection_t      *c,
                      xcb_xkb_device_spec_t  deviceSpec,
                      uint8_t                affectInternalRealMods,
                      uint8_t                internalRealMods,
                      uint8_t                affectIgnoreLockRealMods,
                      uint8_t                ignoreLockRealMods,
                      uint16_t               affectInternalVirtualMods,
                      uint16_t               internalVirtualMods,
                      uint16_t               affectIgnoreLockVirtualMods,
                      uint16_t               ignoreLockVirtualMods,
                      uint8_t                mouseKeysDfltBtn,
                      uint8_t                groupsWrap,
                      uint16_t               accessXOptions,
                      uint32_t               affectEnabledControls,
                      uint32_t               enabledControls,
                      uint32_t               changeControls,
                      uint16_t               repeatDelay,
                      uint16_t               repeatInterval,
                      uint16_t               slowKeysDelay,
                      uint16_t               debounceDelay,
                      uint16_t               mouseKeysDelay,
                      uint16_t               mouseKeysInterval,
                      uint16_t               mouseKeysTimeToMax,
                      uint16_t               mouseKeysMaxSpeed,
                      int16_t                mouseKeysCurve,
                      uint16_t               accessXTimeout,
                      uint32_t               accessXTimeoutMask,
                      uint32_t               accessXTimeoutValues,
                      uint16_t               accessXTimeoutOptionsMask,
                      uint16_t               accessXTimeoutOptionsValues,
                      const uint8_t         *perKeyRepeat);

int
xcb_xkb_get_map_map_types_rtrn_length (const xcb_xkb_get_map_reply_t *R,
                                       const xcb_xkb_get_map_map_t *S);

xcb_xkb_key_type_iterator_t
xcb_xkb_get_map_map_types_rtrn_iterator (const xcb_xkb_get_map_reply_t *R,
                                         const xcb_xkb_get_map_map_t *S);

int
xcb_xkb_get_map_map_syms_rtrn_length (const xcb_xkb_get_map_reply_t *R,
                                      const xcb_xkb_get_map_map_t *S);

xcb_xkb_key_sym_map_iterator_t
xcb_xkb_get_map_map_syms_rtrn_iterator (const xcb_xkb_get_map_reply_t *R,
                                        const xcb_xkb_get_map_map_t *S);

uint8_t *
xcb_xkb_get_map_map_acts_rtrn_count (const xcb_xkb_get_map_map_t *S);

int
xcb_xkb_get_map_map_acts_rtrn_count_length (const xcb_xkb_get_map_reply_t *R,
                                            const xcb_xkb_get_map_map_t *S);

xcb_generic_iterator_t
xcb_xkb_get_map_map_acts_rtrn_count_end (const xcb_xkb_get_map_reply_t *R,
                                         const xcb_xkb_get_map_map_t *S);

xcb_xkb_action_t *
xcb_xkb_get_map_map_acts_rtrn_acts (const xcb_xkb_get_map_map_t *S);

int
xcb_xkb_get_map_map_acts_rtrn_acts_length (const xcb_xkb_get_map_reply_t *R,
                                           const xcb_xkb_get_map_map_t *S);

xcb_xkb_action_iterator_t
xcb_xkb_get_map_map_acts_rtrn_acts_iterator (const xcb_xkb_get_map_reply_t *R,
                                             const xcb_xkb_get_map_map_t *S);

xcb_xkb_set_behavior_t *
xcb_xkb_get_map_map_behaviors_rtrn (const xcb_xkb_get_map_map_t *S);

int
xcb_xkb_get_map_map_behaviors_rtrn_length (const xcb_xkb_get_map_reply_t *R,
                                           const xcb_xkb_get_map_map_t *S);

xcb_xkb_set_behavior_iterator_t
xcb_xkb_get_map_map_behaviors_rtrn_iterator (const xcb_xkb_get_map_reply_t *R,
                                             const xcb_xkb_get_map_map_t *S);

uint8_t *
xcb_xkb_get_map_map_vmods_rtrn (const xcb_xkb_get_map_map_t *S);

int
xcb_xkb_get_map_map_vmods_rtrn_length (const xcb_xkb_get_map_reply_t *R,
                                       const xcb_xkb_get_map_map_t *S);

xcb_generic_iterator_t
xcb_xkb_get_map_map_vmods_rtrn_end (const xcb_xkb_get_map_reply_t *R,
                                    const xcb_xkb_get_map_map_t *S);

xcb_xkb_set_explicit_t *
xcb_xkb_get_map_map_explicit_rtrn (const xcb_xkb_get_map_map_t *S);

int
xcb_xkb_get_map_map_explicit_rtrn_length (const xcb_xkb_get_map_reply_t *R,
                                          const xcb_xkb_get_map_map_t *S);

xcb_xkb_set_explicit_iterator_t
xcb_xkb_get_map_map_explicit_rtrn_iterator (const xcb_xkb_get_map_reply_t *R,
                                            const xcb_xkb_get_map_map_t *S);

xcb_xkb_key_mod_map_t *
xcb_xkb_get_map_map_modmap_rtrn (const xcb_xkb_get_map_map_t *S);

int
xcb_xkb_get_map_map_modmap_rtrn_length (const xcb_xkb_get_map_reply_t *R,
                                        const xcb_xkb_get_map_map_t *S);

xcb_xkb_key_mod_map_iterator_t
xcb_xkb_get_map_map_modmap_rtrn_iterator (const xcb_xkb_get_map_reply_t *R,
                                          const xcb_xkb_get_map_map_t *S);

xcb_xkb_key_v_mod_map_t *
xcb_xkb_get_map_map_vmodmap_rtrn (const xcb_xkb_get_map_map_t *S);

int
xcb_xkb_get_map_map_vmodmap_rtrn_length (const xcb_xkb_get_map_reply_t *R,
                                         const xcb_xkb_get_map_map_t *S);

xcb_xkb_key_v_mod_map_iterator_t
xcb_xkb_get_map_map_vmodmap_rtrn_iterator (const xcb_xkb_get_map_reply_t *R,
                                           const xcb_xkb_get_map_map_t *S);

int
xcb_xkb_get_map_map_serialize (void                        **_buffer,
                               uint8_t                       nTypes,
                               uint8_t                       nKeySyms,
                               uint8_t                       nKeyActions,
                               uint16_t                      totalActions,
                               uint8_t                       totalKeyBehaviors,
                               uint16_t                      virtualMods,
                               uint8_t                       totalKeyExplicit,
                               uint8_t                       totalModMapKeys,
                               uint8_t                       totalVModMapKeys,
                               uint16_t                      present,
                               const xcb_xkb_get_map_map_t  *_aux);

int
xcb_xkb_get_map_map_unpack (const void             *_buffer,
                            uint8_t                 nTypes,
                            uint8_t                 nKeySyms,
                            uint8_t                 nKeyActions,
                            uint16_t                totalActions,
                            uint8_t                 totalKeyBehaviors,
                            uint16_t                virtualMods,
                            uint8_t                 totalKeyExplicit,
                            uint8_t                 totalModMapKeys,
                            uint8_t                 totalVModMapKeys,
                            uint16_t                present,
                            xcb_xkb_get_map_map_t  *_aux);

int
xcb_xkb_get_map_map_sizeof (const void  *_buffer,
                            uint8_t      nTypes,
                            uint8_t      nKeySyms,
                            uint8_t      nKeyActions,
                            uint16_t     totalActions,
                            uint8_t      totalKeyBehaviors,
                            uint16_t     virtualMods,
                            uint8_t      totalKeyExplicit,
                            uint8_t      totalModMapKeys,
                            uint8_t      totalVModMapKeys,
                            uint16_t     present);

int
xcb_xkb_get_map_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xkb_get_map_cookie_t
xcb_xkb_get_map (xcb_connection_t      *c,
                 xcb_xkb_device_spec_t  deviceSpec,
                 uint16_t               full,
                 uint16_t               partial,
                 uint8_t                firstType,
                 uint8_t                nTypes,
                 xcb_keycode_t          firstKeySym,
                 uint8_t                nKeySyms,
                 xcb_keycode_t          firstKeyAction,
                 uint8_t                nKeyActions,
                 xcb_keycode_t          firstKeyBehavior,
                 uint8_t                nKeyBehaviors,
                 uint16_t               virtualMods,
                 xcb_keycode_t          firstKeyExplicit,
                 uint8_t                nKeyExplicit,
                 xcb_keycode_t          firstModMapKey,
                 uint8_t                nModMapKeys,
                 xcb_keycode_t          firstVModMapKey,
                 uint8_t                nVModMapKeys);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_xkb_get_map_cookie_t
xcb_xkb_get_map_unchecked (xcb_connection_t      *c,
                           xcb_xkb_device_spec_t  deviceSpec,
                           uint16_t               full,
                           uint16_t               partial,
                           uint8_t                firstType,
                           uint8_t                nTypes,
                           xcb_keycode_t          firstKeySym,
                           uint8_t                nKeySyms,
                           xcb_keycode_t          firstKeyAction,
                           uint8_t                nKeyActions,
                           xcb_keycode_t          firstKeyBehavior,
                           uint8_t                nKeyBehaviors,
                           uint16_t               virtualMods,
                           xcb_keycode_t          firstKeyExplicit,
                           uint8_t                nKeyExplicit,
                           xcb_keycode_t          firstModMapKey,
                           uint8_t                nModMapKeys,
                           xcb_keycode_t          firstVModMapKey,
                           uint8_t                nVModMapKeys);

void *
xcb_xkb_get_map_map (const xcb_xkb_get_map_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xkb_get_map_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xkb_get_map_reply_t *
xcb_xkb_get_map_reply (xcb_connection_t          *c,
                       xcb_xkb_get_map_cookie_t   cookie  /**< */,
                       xcb_generic_error_t      **e);

int
xcb_xkb_set_map_values_types_length (const xcb_xkb_set_map_request_t *R,
                                     const xcb_xkb_set_map_values_t *S);

xcb_xkb_set_key_type_iterator_t
xcb_xkb_set_map_values_types_iterator (const xcb_xkb_set_map_request_t *R,
                                       const xcb_xkb_set_map_values_t *S);

int
xcb_xkb_set_map_values_syms_length (const xcb_xkb_set_map_request_t *R,
                                    const xcb_xkb_set_map_values_t *S);

xcb_xkb_key_sym_map_iterator_t
xcb_xkb_set_map_values_syms_iterator (const xcb_xkb_set_map_request_t *R,
                                      const xcb_xkb_set_map_values_t *S);

uint8_t *
xcb_xkb_set_map_values_actions_count (const xcb_xkb_set_map_values_t *S);

int
xcb_xkb_set_map_values_actions_count_length (const xcb_xkb_set_map_request_t *R,
                                             const xcb_xkb_set_map_values_t *S);

xcb_generic_iterator_t
xcb_xkb_set_map_values_actions_count_end (const xcb_xkb_set_map_request_t *R,
                                          const xcb_xkb_set_map_values_t *S);

xcb_xkb_action_t *
xcb_xkb_set_map_values_actions (const xcb_xkb_set_map_values_t *S);

int
xcb_xkb_set_map_values_actions_length (const xcb_xkb_set_map_request_t *R,
                                       const xcb_xkb_set_map_values_t *S);

xcb_xkb_action_iterator_t
xcb_xkb_set_map_values_actions_iterator (const xcb_xkb_set_map_request_t *R,
                                         const xcb_xkb_set_map_values_t *S);

xcb_xkb_set_behavior_t *
xcb_xkb_set_map_values_behaviors (const xcb_xkb_set_map_values_t *S);

int
xcb_xkb_set_map_values_behaviors_length (const xcb_xkb_set_map_request_t *R,
                                         const xcb_xkb_set_map_values_t *S);

xcb_xkb_set_behavior_iterator_t
xcb_xkb_set_map_values_behaviors_iterator (const xcb_xkb_set_map_request_t *R,
                                           const xcb_xkb_set_map_values_t *S);

uint8_t *
xcb_xkb_set_map_values_vmods (const xcb_xkb_set_map_values_t *S);

int
xcb_xkb_set_map_values_vmods_length (const xcb_xkb_set_map_request_t *R,
                                     const xcb_xkb_set_map_values_t *S);

xcb_generic_iterator_t
xcb_xkb_set_map_values_vmods_end (const xcb_xkb_set_map_request_t *R,
                                  const xcb_xkb_set_map_values_t *S);

xcb_xkb_set_explicit_t *
xcb_xkb_set_map_values_explicit (const xcb_xkb_set_map_values_t *S);

int
xcb_xkb_set_map_values_explicit_length (const xcb_xkb_set_map_request_t *R,
                                        const xcb_xkb_set_map_values_t *S);

xcb_xkb_set_explicit_iterator_t
xcb_xkb_set_map_values_explicit_iterator (const xcb_xkb_set_map_request_t *R,
                                          const xcb_xkb_set_map_values_t *S);

xcb_xkb_key_mod_map_t *
xcb_xkb_set_map_values_modmap (const xcb_xkb_set_map_values_t *S);

int
xcb_xkb_set_map_values_modmap_length (const xcb_xkb_set_map_request_t *R,
                                      const xcb_xkb_set_map_values_t *S);

xcb_xkb_key_mod_map_iterator_t
xcb_xkb_set_map_values_modmap_iterator (const xcb_xkb_set_map_request_t *R,
                                        const xcb_xkb_set_map_values_t *S);

xcb_xkb_key_v_mod_map_t *
xcb_xkb_set_map_values_vmodmap (const xcb_xkb_set_map_values_t *S);

int
xcb_xkb_set_map_values_vmodmap_length (const xcb_xkb_set_map_request_t *R,
                                       const xcb_xkb_set_map_values_t *S);

xcb_xkb_key_v_mod_map_iterator_t
xcb_xkb_set_map_values_vmodmap_iterator (const xcb_xkb_set_map_request_t *R,
                                         const xcb_xkb_set_map_values_t *S);

int
xcb_xkb_set_map_values_serialize (void                           **_buffer,
                                  uint8_t                          nTypes,
                                  uint8_t                          nKeySyms,
                                  uint8_t                          nKeyActions,
                                  uint16_t                         totalActions,
                                  uint8_t                          totalKeyBehaviors,
                                  uint16_t                         virtualMods,
                                  uint8_t                          totalKeyExplicit,
                                  uint8_t                          totalModMapKeys,
                                  uint8_t                          totalVModMapKeys,
                                  uint16_t                         present,
                                  const xcb_xkb_set_map_values_t  *_aux);

int
xcb_xkb_set_map_values_unpack (const void                *_buffer,
                               uint8_t                    nTypes,
                               uint8_t                    nKeySyms,
                               uint8_t                    nKeyActions,
                               uint16_t                   totalActions,
                               uint8_t                    totalKeyBehaviors,
                               uint16_t                   virtualMods,
                               uint8_t                    totalKeyExplicit,
                               uint8_t                    totalModMapKeys,
                               uint8_t                    totalVModMapKeys,
                               uint16_t                   present,
                               xcb_xkb_set_map_values_t  *_aux);

int
xcb_xkb_set_map_values_sizeof (const void  *_buffer,
                               uint8_t      nTypes,
                               uint8_t      nKeySyms,
                               uint8_t      nKeyActions,
                               uint16_t     totalActions,
                               uint8_t      totalKeyBehaviors,
                               uint16_t     virtualMods,
                               uint8_t      totalKeyExplicit,
                               uint8_t      totalModMapKeys,
                               uint8_t      totalVModMapKeys,
                               uint16_t     present);

int
xcb_xkb_set_map_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_xkb_set_map_checked (xcb_connection_t      *c,
                         xcb_xkb_device_spec_t  deviceSpec,
                         uint16_t               present,
                         uint16_t               flags,
                         xcb_keycode_t          minKeyCode,
                         xcb_keycode_t          maxKeyCode,
                         uint8_t                firstType,
                         uint8_t                nTypes,
                         xcb_keycode_t          firstKeySym,
                         uint8_t                nKeySyms,
                         uint16_t               totalSyms,
                         xcb_keycode_t          firstKeyAction,
                         uint8_t                nKeyActions,
                         uint16_t               totalActions,
                         xcb_keycode_t          firstKeyBehavior,
                         uint8_t                nKeyBehaviors,
                         uint8_t                totalKeyBehaviors,
                         xcb_keycode_t          firstKeyExplicit,
                         uint8_t                nKeyExplicit,
                         uint8_t                totalKeyExplicit,
                         xcb_keycode_t          firstModMapKey,
                         uint8_t                nModMapKeys,
                         uint8_t                totalModMapKeys,
                         xcb_keycode_t          firstVModMapKey,
                         uint8_t                nVModMapKeys,
                         uint8_t                totalVModMapKeys,
                         uint16_t               virtualMods,
                         const void            *values);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xkb_set_map (xcb_connection_t      *c,
                 xcb_xkb_device_spec_t  deviceSpec,
                 uint16_t               present,
                 uint16_t               flags,
                 xcb_keycode_t          minKeyCode,
                 xcb_keycode_t          maxKeyCode,
                 uint8_t                firstType,
                 uint8_t                nTypes,
                 xcb_keycode_t          firstKeySym,
                 uint8_t                nKeySyms,
                 uint16_t               totalSyms,
                 xcb_keycode_t          firstKeyAction,
                 uint8_t                nKeyActions,
                 uint16_t               totalActions,
                 xcb_keycode_t          firstKeyBehavior,
                 uint8_t                nKeyBehaviors,
                 uint8_t                totalKeyBehaviors,
                 xcb_keycode_t          firstKeyExplicit,
                 uint8_t                nKeyExplicit,
                 uint8_t                totalKeyExplicit,
                 xcb_keycode_t          firstModMapKey,
                 uint8_t                nModMapKeys,
                 uint8_t                totalModMapKeys,
                 xcb_keycode_t          firstVModMapKey,
                 uint8_t                nVModMapKeys,
                 uint8_t                totalVModMapKeys,
                 uint16_t               virtualMods,
                 const void            *values);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_xkb_set_map_aux_checked (xcb_connection_t               *c,
                             xcb_xkb_device_spec_t           deviceSpec,
                             uint16_t                        present,
                             uint16_t                        flags,
                             xcb_keycode_t                   minKeyCode,
                             xcb_keycode_t                   maxKeyCode,
                             uint8_t                         firstType,
                             uint8_t                         nTypes,
                             xcb_keycode_t                   firstKeySym,
                             uint8_t                         nKeySyms,
                             uint16_t                        totalSyms,
                             xcb_keycode_t                   firstKeyAction,
                             uint8_t                         nKeyActions,
                             uint16_t                        totalActions,
                             xcb_keycode_t                   firstKeyBehavior,
                             uint8_t                         nKeyBehaviors,
                             uint8_t                         totalKeyBehaviors,
                             xcb_keycode_t                   firstKeyExplicit,
                             uint8_t                         nKeyExplicit,
                             uint8_t                         totalKeyExplicit,
                             xcb_keycode_t                   firstModMapKey,
                             uint8_t                         nModMapKeys,
                             uint8_t                         totalModMapKeys,
                             xcb_keycode_t                   firstVModMapKey,
                             uint8_t                         nVModMapKeys,
                             uint8_t                         totalVModMapKeys,
                             uint16_t                        virtualMods,
                             const xcb_xkb_set_map_values_t *values);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xkb_set_map_aux (xcb_connection_t               *c,
                     xcb_xkb_device_spec_t           deviceSpec,
                     uint16_t                        present,
                     uint16_t                        flags,
                     xcb_keycode_t                   minKeyCode,
                     xcb_keycode_t                   maxKeyCode,
                     uint8_t                         firstType,
                     uint8_t                         nTypes,
                     xcb_keycode_t                   firstKeySym,
                     uint8_t                         nKeySyms,
                     uint16_t                        totalSyms,
                     xcb_keycode_t                   firstKeyAction,
                     uint8_t                         nKeyActions,
                     uint16_t                        totalActions,
                     xcb_keycode_t                   firstKeyBehavior,
                     uint8_t                         nKeyBehaviors,
                     uint8_t                         totalKeyBehaviors,
                     xcb_keycode_t                   firstKeyExplicit,
                     uint8_t                         nKeyExplicit,
                     uint8_t                         totalKeyExplicit,
                     xcb_keycode_t                   firstModMapKey,
                     uint8_t                         nModMapKeys,
                     uint8_t                         totalModMapKeys,
                     xcb_keycode_t                   firstVModMapKey,
                     uint8_t                         nVModMapKeys,
                     uint8_t                         totalVModMapKeys,
                     uint16_t                        virtualMods,
                     const xcb_xkb_set_map_values_t *values);

void *
xcb_xkb_set_map_values (const xcb_xkb_set_map_request_t *R);

int
xcb_xkb_get_compat_map_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xkb_get_compat_map_cookie_t
xcb_xkb_get_compat_map (xcb_connection_t      *c,
                        xcb_xkb_device_spec_t  deviceSpec,
                        uint8_t                groups,
                        uint8_t                getAllSI,
                        uint16_t               firstSI,
                        uint16_t               nSI);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_xkb_get_compat_map_cookie_t
xcb_xkb_get_compat_map_unchecked (xcb_connection_t      *c,
                                  xcb_xkb_device_spec_t  deviceSpec,
                                  uint8_t                groups,
                                  uint8_t                getAllSI,
                                  uint16_t               firstSI,
                                  uint16_t               nSI);

xcb_xkb_sym_interpret_t *
xcb_xkb_get_compat_map_si_rtrn (const xcb_xkb_get_compat_map_reply_t *R);

int
xcb_xkb_get_compat_map_si_rtrn_length (const xcb_xkb_get_compat_map_reply_t *R);

xcb_xkb_sym_interpret_iterator_t
xcb_xkb_get_compat_map_si_rtrn_iterator (const xcb_xkb_get_compat_map_reply_t *R);

xcb_xkb_mod_def_t *
xcb_xkb_get_compat_map_group_rtrn (const xcb_xkb_get_compat_map_reply_t *R);

int
xcb_xkb_get_compat_map_group_rtrn_length (const xcb_xkb_get_compat_map_reply_t *R);

xcb_xkb_mod_def_iterator_t
xcb_xkb_get_compat_map_group_rtrn_iterator (const xcb_xkb_get_compat_map_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xkb_get_compat_map_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xkb_get_compat_map_reply_t *
xcb_xkb_get_compat_map_reply (xcb_connection_t                 *c,
                              xcb_xkb_get_compat_map_cookie_t   cookie  /**< */,
                              xcb_generic_error_t             **e);

int
xcb_xkb_set_compat_map_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_xkb_set_compat_map_checked (xcb_connection_t              *c,
                                xcb_xkb_device_spec_t          deviceSpec,
                                uint8_t                        recomputeActions,
                                uint8_t                        truncateSI,
                                uint8_t                        groups,
                                uint16_t                       firstSI,
                                uint16_t                       nSI,
                                const xcb_xkb_sym_interpret_t *si,
                                const xcb_xkb_mod_def_t       *groupMaps);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xkb_set_compat_map (xcb_connection_t              *c,
                        xcb_xkb_device_spec_t          deviceSpec,
                        uint8_t                        recomputeActions,
                        uint8_t                        truncateSI,
                        uint8_t                        groups,
                        uint16_t                       firstSI,
                        uint16_t                       nSI,
                        const xcb_xkb_sym_interpret_t *si,
                        const xcb_xkb_mod_def_t       *groupMaps);

xcb_xkb_sym_interpret_t *
xcb_xkb_set_compat_map_si (const xcb_xkb_set_compat_map_request_t *R);

int
xcb_xkb_set_compat_map_si_length (const xcb_xkb_set_compat_map_request_t *R);

xcb_xkb_sym_interpret_iterator_t
xcb_xkb_set_compat_map_si_iterator (const xcb_xkb_set_compat_map_request_t *R);

xcb_xkb_mod_def_t *
xcb_xkb_set_compat_map_group_maps (const xcb_xkb_set_compat_map_request_t *R);

int
xcb_xkb_set_compat_map_group_maps_length (const xcb_xkb_set_compat_map_request_t *R);

xcb_xkb_mod_def_iterator_t
xcb_xkb_set_compat_map_group_maps_iterator (const xcb_xkb_set_compat_map_request_t *R);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xkb_get_indicator_state_cookie_t
xcb_xkb_get_indicator_state (xcb_connection_t      *c,
                             xcb_xkb_device_spec_t  deviceSpec);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_xkb_get_indicator_state_cookie_t
xcb_xkb_get_indicator_state_unchecked (xcb_connection_t      *c,
                                       xcb_xkb_device_spec_t  deviceSpec);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xkb_get_indicator_state_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xkb_get_indicator_state_reply_t *
xcb_xkb_get_indicator_state_reply (xcb_connection_t                      *c,
                                   xcb_xkb_get_indicator_state_cookie_t   cookie  /**< */,
                                   xcb_generic_error_t                  **e);

int
xcb_xkb_get_indicator_map_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xkb_get_indicator_map_cookie_t
xcb_xkb_get_indicator_map (xcb_connection_t      *c,
                           xcb_xkb_device_spec_t  deviceSpec,
                           uint32_t               which);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_xkb_get_indicator_map_cookie_t
xcb_xkb_get_indicator_map_unchecked (xcb_connection_t      *c,
                                     xcb_xkb_device_spec_t  deviceSpec,
                                     uint32_t               which);

xcb_xkb_indicator_map_t *
xcb_xkb_get_indicator_map_maps (const xcb_xkb_get_indicator_map_reply_t *R);

int
xcb_xkb_get_indicator_map_maps_length (const xcb_xkb_get_indicator_map_reply_t *R);

xcb_xkb_indicator_map_iterator_t
xcb_xkb_get_indicator_map_maps_iterator (const xcb_xkb_get_indicator_map_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xkb_get_indicator_map_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xkb_get_indicator_map_reply_t *
xcb_xkb_get_indicator_map_reply (xcb_connection_t                    *c,
                                 xcb_xkb_get_indicator_map_cookie_t   cookie  /**< */,
                                 xcb_generic_error_t                **e);

int
xcb_xkb_set_indicator_map_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_xkb_set_indicator_map_checked (xcb_connection_t              *c,
                                   xcb_xkb_device_spec_t          deviceSpec,
                                   uint32_t                       which,
                                   const xcb_xkb_indicator_map_t *maps);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xkb_set_indicator_map (xcb_connection_t              *c,
                           xcb_xkb_device_spec_t          deviceSpec,
                           uint32_t                       which,
                           const xcb_xkb_indicator_map_t *maps);

xcb_xkb_indicator_map_t *
xcb_xkb_set_indicator_map_maps (const xcb_xkb_set_indicator_map_request_t *R);

int
xcb_xkb_set_indicator_map_maps_length (const xcb_xkb_set_indicator_map_request_t *R);

xcb_xkb_indicator_map_iterator_t
xcb_xkb_set_indicator_map_maps_iterator (const xcb_xkb_set_indicator_map_request_t *R);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xkb_get_named_indicator_cookie_t
xcb_xkb_get_named_indicator (xcb_connection_t         *c,
                             xcb_xkb_device_spec_t     deviceSpec,
                             xcb_xkb_led_class_spec_t  ledClass,
                             xcb_xkb_id_spec_t         ledID,
                             xcb_atom_t                indicator);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_xkb_get_named_indicator_cookie_t
xcb_xkb_get_named_indicator_unchecked (xcb_connection_t         *c,
                                       xcb_xkb_device_spec_t     deviceSpec,
                                       xcb_xkb_led_class_spec_t  ledClass,
                                       xcb_xkb_id_spec_t         ledID,
                                       xcb_atom_t                indicator);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xkb_get_named_indicator_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xkb_get_named_indicator_reply_t *
xcb_xkb_get_named_indicator_reply (xcb_connection_t                      *c,
                                   xcb_xkb_get_named_indicator_cookie_t   cookie  /**< */,
                                   xcb_generic_error_t                  **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_xkb_set_named_indicator_checked (xcb_connection_t         *c,
                                     xcb_xkb_device_spec_t     deviceSpec,
                                     xcb_xkb_led_class_spec_t  ledClass,
                                     xcb_xkb_id_spec_t         ledID,
                                     xcb_atom_t                indicator,
                                     uint8_t                   setState,
                                     uint8_t                   on,
                                     uint8_t                   setMap,
                                     uint8_t                   createMap,
                                     uint8_t                   map_flags,
                                     uint8_t                   map_whichGroups,
                                     uint8_t                   map_groups,
                                     uint8_t                   map_whichMods,
                                     uint8_t                   map_realMods,
                                     uint16_t                  map_vmods,
                                     uint32_t                  map_ctrls);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xkb_set_named_indicator (xcb_connection_t         *c,
                             xcb_xkb_device_spec_t     deviceSpec,
                             xcb_xkb_led_class_spec_t  ledClass,
                             xcb_xkb_id_spec_t         ledID,
                             xcb_atom_t                indicator,
                             uint8_t                   setState,
                             uint8_t                   on,
                             uint8_t                   setMap,
                             uint8_t                   createMap,
                             uint8_t                   map_flags,
                             uint8_t                   map_whichGroups,
                             uint8_t                   map_groups,
                             uint8_t                   map_whichMods,
                             uint8_t                   map_realMods,
                             uint16_t                  map_vmods,
                             uint32_t                  map_ctrls);

xcb_atom_t *
xcb_xkb_get_names_value_list_type_names (const xcb_xkb_get_names_value_list_t *S);

int
xcb_xkb_get_names_value_list_type_names_length (const xcb_xkb_get_names_reply_t *R,
                                                const xcb_xkb_get_names_value_list_t *S);

xcb_generic_iterator_t
xcb_xkb_get_names_value_list_type_names_end (const xcb_xkb_get_names_reply_t *R,
                                             const xcb_xkb_get_names_value_list_t *S);

uint8_t *
xcb_xkb_get_names_value_list_n_levels_per_type (const xcb_xkb_get_names_value_list_t *S);

int
xcb_xkb_get_names_value_list_n_levels_per_type_length (const xcb_xkb_get_names_reply_t *R,
                                                       const xcb_xkb_get_names_value_list_t *S);

xcb_generic_iterator_t
xcb_xkb_get_names_value_list_n_levels_per_type_end (const xcb_xkb_get_names_reply_t *R,
                                                    const xcb_xkb_get_names_value_list_t *S);

xcb_atom_t *
xcb_xkb_get_names_value_list_kt_level_names (const xcb_xkb_get_names_value_list_t *S);

int
xcb_xkb_get_names_value_list_kt_level_names_length (const xcb_xkb_get_names_reply_t *R,
                                                    const xcb_xkb_get_names_value_list_t *S);

xcb_generic_iterator_t
xcb_xkb_get_names_value_list_kt_level_names_end (const xcb_xkb_get_names_reply_t *R,
                                                 const xcb_xkb_get_names_value_list_t *S);

xcb_atom_t *
xcb_xkb_get_names_value_list_indicator_names (const xcb_xkb_get_names_value_list_t *S);

int
xcb_xkb_get_names_value_list_indicator_names_length (const xcb_xkb_get_names_reply_t *R,
                                                     const xcb_xkb_get_names_value_list_t *S);

xcb_generic_iterator_t
xcb_xkb_get_names_value_list_indicator_names_end (const xcb_xkb_get_names_reply_t *R,
                                                  const xcb_xkb_get_names_value_list_t *S);

xcb_atom_t *
xcb_xkb_get_names_value_list_virtual_mod_names (const xcb_xkb_get_names_value_list_t *S);

int
xcb_xkb_get_names_value_list_virtual_mod_names_length (const xcb_xkb_get_names_reply_t *R,
                                                       const xcb_xkb_get_names_value_list_t *S);

xcb_generic_iterator_t
xcb_xkb_get_names_value_list_virtual_mod_names_end (const xcb_xkb_get_names_reply_t *R,
                                                    const xcb_xkb_get_names_value_list_t *S);

xcb_atom_t *
xcb_xkb_get_names_value_list_groups (const xcb_xkb_get_names_value_list_t *S);

int
xcb_xkb_get_names_value_list_groups_length (const xcb_xkb_get_names_reply_t *R,
                                            const xcb_xkb_get_names_value_list_t *S);

xcb_generic_iterator_t
xcb_xkb_get_names_value_list_groups_end (const xcb_xkb_get_names_reply_t *R,
                                         const xcb_xkb_get_names_value_list_t *S);

xcb_xkb_key_name_t *
xcb_xkb_get_names_value_list_key_names (const xcb_xkb_get_names_value_list_t *S);

int
xcb_xkb_get_names_value_list_key_names_length (const xcb_xkb_get_names_reply_t *R,
                                               const xcb_xkb_get_names_value_list_t *S);

xcb_xkb_key_name_iterator_t
xcb_xkb_get_names_value_list_key_names_iterator (const xcb_xkb_get_names_reply_t *R,
                                                 const xcb_xkb_get_names_value_list_t *S);

xcb_xkb_key_alias_t *
xcb_xkb_get_names_value_list_key_aliases (const xcb_xkb_get_names_value_list_t *S);

int
xcb_xkb_get_names_value_list_key_aliases_length (const xcb_xkb_get_names_reply_t *R,
                                                 const xcb_xkb_get_names_value_list_t *S);

xcb_xkb_key_alias_iterator_t
xcb_xkb_get_names_value_list_key_aliases_iterator (const xcb_xkb_get_names_reply_t *R,
                                                   const xcb_xkb_get_names_value_list_t *S);

xcb_atom_t *
xcb_xkb_get_names_value_list_radio_group_names (const xcb_xkb_get_names_value_list_t *S);

int
xcb_xkb_get_names_value_list_radio_group_names_length (const xcb_xkb_get_names_reply_t *R,
                                                       const xcb_xkb_get_names_value_list_t *S);

xcb_generic_iterator_t
xcb_xkb_get_names_value_list_radio_group_names_end (const xcb_xkb_get_names_reply_t *R,
                                                    const xcb_xkb_get_names_value_list_t *S);

int
xcb_xkb_get_names_value_list_serialize (void                                 **_buffer,
                                        uint8_t                                nTypes,
                                        uint32_t                               indicators,
                                        uint16_t                               virtualMods,
                                        uint8_t                                groupNames,
                                        uint8_t                                nKeys,
                                        uint8_t                                nKeyAliases,
                                        uint8_t                                nRadioGroups,
                                        uint32_t                               which,
                                        const xcb_xkb_get_names_value_list_t  *_aux);

int
xcb_xkb_get_names_value_list_unpack (const void                      *_buffer,
                                     uint8_t                          nTypes,
                                     uint32_t                         indicators,
                                     uint16_t                         virtualMods,
                                     uint8_t                          groupNames,
                                     uint8_t                          nKeys,
                                     uint8_t                          nKeyAliases,
                                     uint8_t                          nRadioGroups,
                                     uint32_t                         which,
                                     xcb_xkb_get_names_value_list_t  *_aux);

int
xcb_xkb_get_names_value_list_sizeof (const void  *_buffer,
                                     uint8_t      nTypes,
                                     uint32_t     indicators,
                                     uint16_t     virtualMods,
                                     uint8_t      groupNames,
                                     uint8_t      nKeys,
                                     uint8_t      nKeyAliases,
                                     uint8_t      nRadioGroups,
                                     uint32_t     which);

int
xcb_xkb_get_names_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xkb_get_names_cookie_t
xcb_xkb_get_names (xcb_connection_t      *c,
                   xcb_xkb_device_spec_t  deviceSpec,
                   uint32_t               which);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_xkb_get_names_cookie_t
xcb_xkb_get_names_unchecked (xcb_connection_t      *c,
                             xcb_xkb_device_spec_t  deviceSpec,
                             uint32_t               which);

void *
xcb_xkb_get_names_value_list (const xcb_xkb_get_names_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xkb_get_names_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xkb_get_names_reply_t *
xcb_xkb_get_names_reply (xcb_connection_t            *c,
                         xcb_xkb_get_names_cookie_t   cookie  /**< */,
                         xcb_generic_error_t        **e);

xcb_atom_t *
xcb_xkb_set_names_values_type_names (const xcb_xkb_set_names_values_t *S);

int
xcb_xkb_set_names_values_type_names_length (const xcb_xkb_set_names_request_t *R,
                                            const xcb_xkb_set_names_values_t *S);

xcb_generic_iterator_t
xcb_xkb_set_names_values_type_names_end (const xcb_xkb_set_names_request_t *R,
                                         const xcb_xkb_set_names_values_t *S);

uint8_t *
xcb_xkb_set_names_values_n_levels_per_type (const xcb_xkb_set_names_values_t *S);

int
xcb_xkb_set_names_values_n_levels_per_type_length (const xcb_xkb_set_names_request_t *R,
                                                   const xcb_xkb_set_names_values_t *S);

xcb_generic_iterator_t
xcb_xkb_set_names_values_n_levels_per_type_end (const xcb_xkb_set_names_request_t *R,
                                                const xcb_xkb_set_names_values_t *S);

xcb_atom_t *
xcb_xkb_set_names_values_kt_level_names (const xcb_xkb_set_names_values_t *S);

int
xcb_xkb_set_names_values_kt_level_names_length (const xcb_xkb_set_names_request_t *R,
                                                const xcb_xkb_set_names_values_t *S);

xcb_generic_iterator_t
xcb_xkb_set_names_values_kt_level_names_end (const xcb_xkb_set_names_request_t *R,
                                             const xcb_xkb_set_names_values_t *S);

xcb_atom_t *
xcb_xkb_set_names_values_indicator_names (const xcb_xkb_set_names_values_t *S);

int
xcb_xkb_set_names_values_indicator_names_length (const xcb_xkb_set_names_request_t *R,
                                                 const xcb_xkb_set_names_values_t *S);

xcb_generic_iterator_t
xcb_xkb_set_names_values_indicator_names_end (const xcb_xkb_set_names_request_t *R,
                                              const xcb_xkb_set_names_values_t *S);

xcb_atom_t *
xcb_xkb_set_names_values_virtual_mod_names (const xcb_xkb_set_names_values_t *S);

int
xcb_xkb_set_names_values_virtual_mod_names_length (const xcb_xkb_set_names_request_t *R,
                                                   const xcb_xkb_set_names_values_t *S);

xcb_generic_iterator_t
xcb_xkb_set_names_values_virtual_mod_names_end (const xcb_xkb_set_names_request_t *R,
                                                const xcb_xkb_set_names_values_t *S);

xcb_atom_t *
xcb_xkb_set_names_values_groups (const xcb_xkb_set_names_values_t *S);

int
xcb_xkb_set_names_values_groups_length (const xcb_xkb_set_names_request_t *R,
                                        const xcb_xkb_set_names_values_t *S);

xcb_generic_iterator_t
xcb_xkb_set_names_values_groups_end (const xcb_xkb_set_names_request_t *R,
                                     const xcb_xkb_set_names_values_t *S);

xcb_xkb_key_name_t *
xcb_xkb_set_names_values_key_names (const xcb_xkb_set_names_values_t *S);

int
xcb_xkb_set_names_values_key_names_length (const xcb_xkb_set_names_request_t *R,
                                           const xcb_xkb_set_names_values_t *S);

xcb_xkb_key_name_iterator_t
xcb_xkb_set_names_values_key_names_iterator (const xcb_xkb_set_names_request_t *R,
                                             const xcb_xkb_set_names_values_t *S);

xcb_xkb_key_alias_t *
xcb_xkb_set_names_values_key_aliases (const xcb_xkb_set_names_values_t *S);

int
xcb_xkb_set_names_values_key_aliases_length (const xcb_xkb_set_names_request_t *R,
                                             const xcb_xkb_set_names_values_t *S);

xcb_xkb_key_alias_iterator_t
xcb_xkb_set_names_values_key_aliases_iterator (const xcb_xkb_set_names_request_t *R,
                                               const xcb_xkb_set_names_values_t *S);

xcb_atom_t *
xcb_xkb_set_names_values_radio_group_names (const xcb_xkb_set_names_values_t *S);

int
xcb_xkb_set_names_values_radio_group_names_length (const xcb_xkb_set_names_request_t *R,
                                                   const xcb_xkb_set_names_values_t *S);

xcb_generic_iterator_t
xcb_xkb_set_names_values_radio_group_names_end (const xcb_xkb_set_names_request_t *R,
                                                const xcb_xkb_set_names_values_t *S);

int
xcb_xkb_set_names_values_serialize (void                             **_buffer,
                                    uint8_t                            nTypes,
                                    uint32_t                           indicators,
                                    uint16_t                           virtualMods,
                                    uint8_t                            groupNames,
                                    uint8_t                            nKeys,
                                    uint8_t                            nKeyAliases,
                                    uint8_t                            nRadioGroups,
                                    uint32_t                           which,
                                    const xcb_xkb_set_names_values_t  *_aux);

int
xcb_xkb_set_names_values_unpack (const void                  *_buffer,
                                 uint8_t                      nTypes,
                                 uint32_t                     indicators,
                                 uint16_t                     virtualMods,
                                 uint8_t                      groupNames,
                                 uint8_t                      nKeys,
                                 uint8_t                      nKeyAliases,
                                 uint8_t                      nRadioGroups,
                                 uint32_t                     which,
                                 xcb_xkb_set_names_values_t  *_aux);

int
xcb_xkb_set_names_values_sizeof (const void  *_buffer,
                                 uint8_t      nTypes,
                                 uint32_t     indicators,
                                 uint16_t     virtualMods,
                                 uint8_t      groupNames,
                                 uint8_t      nKeys,
                                 uint8_t      nKeyAliases,
                                 uint8_t      nRadioGroups,
                                 uint32_t     which);

int
xcb_xkb_set_names_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_xkb_set_names_checked (xcb_connection_t      *c,
                           xcb_xkb_device_spec_t  deviceSpec,
                           uint16_t               virtualMods,
                           uint32_t               which,
                           uint8_t                firstType,
                           uint8_t                nTypes,
                           uint8_t                firstKTLevelt,
                           uint8_t                nKTLevels,
                           uint32_t               indicators,
                           uint8_t                groupNames,
                           uint8_t                nRadioGroups,
                           xcb_keycode_t          firstKey,
                           uint8_t                nKeys,
                           uint8_t                nKeyAliases,
                           uint16_t               totalKTLevelNames,
                           const void            *values);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xkb_set_names (xcb_connection_t      *c,
                   xcb_xkb_device_spec_t  deviceSpec,
                   uint16_t               virtualMods,
                   uint32_t               which,
                   uint8_t                firstType,
                   uint8_t                nTypes,
                   uint8_t                firstKTLevelt,
                   uint8_t                nKTLevels,
                   uint32_t               indicators,
                   uint8_t                groupNames,
                   uint8_t                nRadioGroups,
                   xcb_keycode_t          firstKey,
                   uint8_t                nKeys,
                   uint8_t                nKeyAliases,
                   uint16_t               totalKTLevelNames,
                   const void            *values);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_xkb_set_names_aux_checked (xcb_connection_t                 *c,
                               xcb_xkb_device_spec_t             deviceSpec,
                               uint16_t                          virtualMods,
                               uint32_t                          which,
                               uint8_t                           firstType,
                               uint8_t                           nTypes,
                               uint8_t                           firstKTLevelt,
                               uint8_t                           nKTLevels,
                               uint32_t                          indicators,
                               uint8_t                           groupNames,
                               uint8_t                           nRadioGroups,
                               xcb_keycode_t                     firstKey,
                               uint8_t                           nKeys,
                               uint8_t                           nKeyAliases,
                               uint16_t                          totalKTLevelNames,
                               const xcb_xkb_set_names_values_t *values);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xkb_set_names_aux (xcb_connection_t                 *c,
                       xcb_xkb_device_spec_t             deviceSpec,
                       uint16_t                          virtualMods,
                       uint32_t                          which,
                       uint8_t                           firstType,
                       uint8_t                           nTypes,
                       uint8_t                           firstKTLevelt,
                       uint8_t                           nKTLevels,
                       uint32_t                          indicators,
                       uint8_t                           groupNames,
                       uint8_t                           nRadioGroups,
                       xcb_keycode_t                     firstKey,
                       uint8_t                           nKeys,
                       uint8_t                           nKeyAliases,
                       uint16_t                          totalKTLevelNames,
                       const xcb_xkb_set_names_values_t *values);

void *
xcb_xkb_set_names_values (const xcb_xkb_set_names_request_t *R);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xkb_per_client_flags_cookie_t
xcb_xkb_per_client_flags (xcb_connection_t      *c,
                          xcb_xkb_device_spec_t  deviceSpec,
                          uint32_t               change,
                          uint32_t               value,
                          uint32_t               ctrlsToChange,
                          uint32_t               autoCtrls,
                          uint32_t               autoCtrlsValues);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_xkb_per_client_flags_cookie_t
xcb_xkb_per_client_flags_unchecked (xcb_connection_t      *c,
                                    xcb_xkb_device_spec_t  deviceSpec,
                                    uint32_t               change,
                                    uint32_t               value,
                                    uint32_t               ctrlsToChange,
                                    uint32_t               autoCtrls,
                                    uint32_t               autoCtrlsValues);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xkb_per_client_flags_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xkb_per_client_flags_reply_t *
xcb_xkb_per_client_flags_reply (xcb_connection_t                   *c,
                                xcb_xkb_per_client_flags_cookie_t   cookie  /**< */,
                                xcb_generic_error_t               **e);

int
xcb_xkb_list_components_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xkb_list_components_cookie_t
xcb_xkb_list_components (xcb_connection_t      *c,
                         xcb_xkb_device_spec_t  deviceSpec,
                         uint16_t               maxNames);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_xkb_list_components_cookie_t
xcb_xkb_list_components_unchecked (xcb_connection_t      *c,
                                   xcb_xkb_device_spec_t  deviceSpec,
                                   uint16_t               maxNames);

int
xcb_xkb_list_components_keymaps_length (const xcb_xkb_list_components_reply_t *R);

xcb_xkb_listing_iterator_t
xcb_xkb_list_components_keymaps_iterator (const xcb_xkb_list_components_reply_t *R);

int
xcb_xkb_list_components_keycodes_length (const xcb_xkb_list_components_reply_t *R);

xcb_xkb_listing_iterator_t
xcb_xkb_list_components_keycodes_iterator (const xcb_xkb_list_components_reply_t *R);

int
xcb_xkb_list_components_types_length (const xcb_xkb_list_components_reply_t *R);

xcb_xkb_listing_iterator_t
xcb_xkb_list_components_types_iterator (const xcb_xkb_list_components_reply_t *R);

int
xcb_xkb_list_components_compat_maps_length (const xcb_xkb_list_components_reply_t *R);

xcb_xkb_listing_iterator_t
xcb_xkb_list_components_compat_maps_iterator (const xcb_xkb_list_components_reply_t *R);

int
xcb_xkb_list_components_symbols_length (const xcb_xkb_list_components_reply_t *R);

xcb_xkb_listing_iterator_t
xcb_xkb_list_components_symbols_iterator (const xcb_xkb_list_components_reply_t *R);

int
xcb_xkb_list_components_geometries_length (const xcb_xkb_list_components_reply_t *R);

xcb_xkb_listing_iterator_t
xcb_xkb_list_components_geometries_iterator (const xcb_xkb_list_components_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xkb_list_components_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xkb_list_components_reply_t *
xcb_xkb_list_components_reply (xcb_connection_t                  *c,
                               xcb_xkb_list_components_cookie_t   cookie  /**< */,
                               xcb_generic_error_t              **e);

int
xcb_xkb_get_kbd_by_name_replies_types_map_types_rtrn_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                             const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_key_type_iterator_t
xcb_xkb_get_kbd_by_name_replies_types_map_types_rtrn_iterator (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                               const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_types_map_syms_rtrn_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                            const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_key_sym_map_iterator_t
xcb_xkb_get_kbd_by_name_replies_types_map_syms_rtrn_iterator (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                              const xcb_xkb_get_kbd_by_name_replies_t *S);

uint8_t *
xcb_xkb_get_kbd_by_name_replies_types_map_acts_rtrn_count (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_types_map_acts_rtrn_count_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                  const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_generic_iterator_t
xcb_xkb_get_kbd_by_name_replies_types_map_acts_rtrn_count_end (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                               const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_action_t *
xcb_xkb_get_kbd_by_name_replies_types_map_acts_rtrn_acts (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_types_map_acts_rtrn_acts_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                 const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_action_iterator_t
xcb_xkb_get_kbd_by_name_replies_types_map_acts_rtrn_acts_iterator (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                   const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_set_behavior_t *
xcb_xkb_get_kbd_by_name_replies_types_map_behaviors_rtrn (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_types_map_behaviors_rtrn_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                 const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_set_behavior_iterator_t
xcb_xkb_get_kbd_by_name_replies_types_map_behaviors_rtrn_iterator (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                   const xcb_xkb_get_kbd_by_name_replies_t *S);

uint8_t *
xcb_xkb_get_kbd_by_name_replies_types_map_vmods_rtrn (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_types_map_vmods_rtrn_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                             const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_generic_iterator_t
xcb_xkb_get_kbd_by_name_replies_types_map_vmods_rtrn_end (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                          const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_set_explicit_t *
xcb_xkb_get_kbd_by_name_replies_types_map_explicit_rtrn (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_types_map_explicit_rtrn_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_set_explicit_iterator_t
xcb_xkb_get_kbd_by_name_replies_types_map_explicit_rtrn_iterator (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                  const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_key_mod_map_t *
xcb_xkb_get_kbd_by_name_replies_types_map_modmap_rtrn (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_types_map_modmap_rtrn_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                              const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_key_mod_map_iterator_t
xcb_xkb_get_kbd_by_name_replies_types_map_modmap_rtrn_iterator (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_key_v_mod_map_t *
xcb_xkb_get_kbd_by_name_replies_types_map_vmodmap_rtrn (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_types_map_vmodmap_rtrn_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                               const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_key_v_mod_map_iterator_t
xcb_xkb_get_kbd_by_name_replies_types_map_vmodmap_rtrn_iterator (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                 const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_types_map_serialize (void                                              **_buffer,
                                                     uint8_t                                             nTypes,
                                                     uint8_t                                             nKeySyms,
                                                     uint8_t                                             nKeyActions,
                                                     uint16_t                                            totalActions,
                                                     uint8_t                                             totalKeyBehaviors,
                                                     uint16_t                                            virtualMods,
                                                     uint8_t                                             totalKeyExplicit,
                                                     uint8_t                                             totalModMapKeys,
                                                     uint8_t                                             totalVModMapKeys,
                                                     uint16_t                                            present,
                                                     const xcb_xkb_get_kbd_by_name_replies_types_map_t  *_aux);

int
xcb_xkb_get_kbd_by_name_replies_types_map_unpack (const void                                   *_buffer,
                                                  uint8_t                                       nTypes,
                                                  uint8_t                                       nKeySyms,
                                                  uint8_t                                       nKeyActions,
                                                  uint16_t                                      totalActions,
                                                  uint8_t                                       totalKeyBehaviors,
                                                  uint16_t                                      virtualMods,
                                                  uint8_t                                       totalKeyExplicit,
                                                  uint8_t                                       totalModMapKeys,
                                                  uint8_t                                       totalVModMapKeys,
                                                  uint16_t                                      present,
                                                  xcb_xkb_get_kbd_by_name_replies_types_map_t  *_aux);

int
xcb_xkb_get_kbd_by_name_replies_types_map_sizeof (const void  *_buffer,
                                                  uint8_t      nTypes,
                                                  uint8_t      nKeySyms,
                                                  uint8_t      nKeyActions,
                                                  uint16_t     totalActions,
                                                  uint8_t      totalKeyBehaviors,
                                                  uint16_t     virtualMods,
                                                  uint8_t      totalKeyExplicit,
                                                  uint8_t      totalModMapKeys,
                                                  uint8_t      totalVModMapKeys,
                                                  uint16_t     present);

xcb_atom_t *
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_type_names (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_type_names_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                        const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_generic_iterator_t
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_type_names_end (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                     const xcb_xkb_get_kbd_by_name_replies_t *S);

uint8_t *
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_n_levels_per_type (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_n_levels_per_type_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                               const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_generic_iterator_t
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_n_levels_per_type_end (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                            const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_atom_t *
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_kt_level_names (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_kt_level_names_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                            const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_generic_iterator_t
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_kt_level_names_end (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                         const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_atom_t *
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_indicator_names (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_indicator_names_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                             const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_generic_iterator_t
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_indicator_names_end (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                          const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_atom_t *
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_virtual_mod_names (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_virtual_mod_names_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                               const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_generic_iterator_t
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_virtual_mod_names_end (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                            const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_atom_t *
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_groups (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_groups_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                    const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_generic_iterator_t
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_groups_end (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                 const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_key_name_t *
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_key_names (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_key_names_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                       const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_key_name_iterator_t
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_key_names_iterator (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                         const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_key_alias_t *
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_key_aliases (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_key_aliases_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                         const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_key_alias_iterator_t
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_key_aliases_iterator (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                           const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_atom_t *
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_radio_group_names (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_radio_group_names_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                               const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_generic_iterator_t
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_radio_group_names_end (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                            const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_serialize (void                                                         **_buffer,
                                                                uint8_t                                                        nTypes,
                                                                uint32_t                                                       indicators,
                                                                uint16_t                                                       virtualMods,
                                                                uint8_t                                                        groupNames,
                                                                uint8_t                                                        nKeys,
                                                                uint8_t                                                        nKeyAliases,
                                                                uint8_t                                                        nRadioGroups,
                                                                uint32_t                                                       which,
                                                                const xcb_xkb_get_kbd_by_name_replies_key_names_value_list_t  *_aux);

int
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_unpack (const void                                              *_buffer,
                                                             uint8_t                                                  nTypes,
                                                             uint32_t                                                 indicators,
                                                             uint16_t                                                 virtualMods,
                                                             uint8_t                                                  groupNames,
                                                             uint8_t                                                  nKeys,
                                                             uint8_t                                                  nKeyAliases,
                                                             uint8_t                                                  nRadioGroups,
                                                             uint32_t                                                 which,
                                                             xcb_xkb_get_kbd_by_name_replies_key_names_value_list_t  *_aux);

int
xcb_xkb_get_kbd_by_name_replies_key_names_value_list_sizeof (const void  *_buffer,
                                                             uint8_t      nTypes,
                                                             uint32_t     indicators,
                                                             uint16_t     virtualMods,
                                                             uint8_t      groupNames,
                                                             uint8_t      nKeys,
                                                             uint8_t      nKeyAliases,
                                                             uint8_t      nRadioGroups,
                                                             uint32_t     which);

xcb_xkb_sym_interpret_t *
xcb_xkb_get_kbd_by_name_replies_compat_map_si_rtrn (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_compat_map_si_rtrn_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                           const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_sym_interpret_iterator_t
xcb_xkb_get_kbd_by_name_replies_compat_map_si_rtrn_iterator (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                             const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_mod_def_t *
xcb_xkb_get_kbd_by_name_replies_compat_map_group_rtrn (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_compat_map_group_rtrn_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                              const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_mod_def_iterator_t
xcb_xkb_get_kbd_by_name_replies_compat_map_group_rtrn_iterator (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                                const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_indicator_map_t *
xcb_xkb_get_kbd_by_name_replies_indicator_maps_maps (const xcb_xkb_get_kbd_by_name_replies_t *S);

int
xcb_xkb_get_kbd_by_name_replies_indicator_maps_maps_length (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                            const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_indicator_map_iterator_t
xcb_xkb_get_kbd_by_name_replies_indicator_maps_maps_iterator (const xcb_xkb_get_kbd_by_name_reply_t *R,
                                                              const xcb_xkb_get_kbd_by_name_replies_t *S);

xcb_xkb_get_kbd_by_name_replies_key_names_value_list_t *
xcb_xkb_get_kbd_by_name_replies_key_names_value_list (const xcb_xkb_get_kbd_by_name_replies_t *R);

xcb_xkb_counted_string_16_t *
xcb_xkb_get_kbd_by_name_replies_geometry_label_font (const xcb_xkb_get_kbd_by_name_replies_t *R);

int
xcb_xkb_get_kbd_by_name_replies_serialize (void                                    **_buffer,
                                           uint16_t                                  reported,
                                           const xcb_xkb_get_kbd_by_name_replies_t  *_aux);

int
xcb_xkb_get_kbd_by_name_replies_unpack (const void                         *_buffer,
                                        uint16_t                            reported,
                                        xcb_xkb_get_kbd_by_name_replies_t  *_aux);

int
xcb_xkb_get_kbd_by_name_replies_sizeof (const void  *_buffer,
                                        uint16_t     reported);

int
xcb_xkb_get_kbd_by_name_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xkb_get_kbd_by_name_cookie_t
xcb_xkb_get_kbd_by_name (xcb_connection_t      *c,
                         xcb_xkb_device_spec_t  deviceSpec,
                         uint16_t               need,
                         uint16_t               want,
                         uint8_t                load);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_xkb_get_kbd_by_name_cookie_t
xcb_xkb_get_kbd_by_name_unchecked (xcb_connection_t      *c,
                                   xcb_xkb_device_spec_t  deviceSpec,
                                   uint16_t               need,
                                   uint16_t               want,
                                   uint8_t                load);

void *
xcb_xkb_get_kbd_by_name_replies (const xcb_xkb_get_kbd_by_name_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xkb_get_kbd_by_name_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xkb_get_kbd_by_name_reply_t *
xcb_xkb_get_kbd_by_name_reply (xcb_connection_t                  *c,
                               xcb_xkb_get_kbd_by_name_cookie_t   cookie  /**< */,
                               xcb_generic_error_t              **e);

int
xcb_xkb_get_device_info_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xkb_get_device_info_cookie_t
xcb_xkb_get_device_info (xcb_connection_t         *c,
                         xcb_xkb_device_spec_t     deviceSpec,
                         uint16_t                  wanted,
                         uint8_t                   allButtons,
                         uint8_t                   firstButton,
                         uint8_t                   nButtons,
                         xcb_xkb_led_class_spec_t  ledClass,
                         xcb_xkb_id_spec_t         ledID);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_xkb_get_device_info_cookie_t
xcb_xkb_get_device_info_unchecked (xcb_connection_t         *c,
                                   xcb_xkb_device_spec_t     deviceSpec,
                                   uint16_t                  wanted,
                                   uint8_t                   allButtons,
                                   uint8_t                   firstButton,
                                   uint8_t                   nButtons,
                                   xcb_xkb_led_class_spec_t  ledClass,
                                   xcb_xkb_id_spec_t         ledID);

xcb_xkb_string8_t *
xcb_xkb_get_device_info_name (const xcb_xkb_get_device_info_reply_t *R);

int
xcb_xkb_get_device_info_name_length (const xcb_xkb_get_device_info_reply_t *R);

xcb_generic_iterator_t
xcb_xkb_get_device_info_name_end (const xcb_xkb_get_device_info_reply_t *R);

xcb_xkb_action_t *
xcb_xkb_get_device_info_btn_actions (const xcb_xkb_get_device_info_reply_t *R);

int
xcb_xkb_get_device_info_btn_actions_length (const xcb_xkb_get_device_info_reply_t *R);

xcb_xkb_action_iterator_t
xcb_xkb_get_device_info_btn_actions_iterator (const xcb_xkb_get_device_info_reply_t *R);

int
xcb_xkb_get_device_info_leds_length (const xcb_xkb_get_device_info_reply_t *R);

xcb_xkb_device_led_info_iterator_t
xcb_xkb_get_device_info_leds_iterator (const xcb_xkb_get_device_info_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xkb_get_device_info_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xkb_get_device_info_reply_t *
xcb_xkb_get_device_info_reply (xcb_connection_t                  *c,
                               xcb_xkb_get_device_info_cookie_t   cookie  /**< */,
                               xcb_generic_error_t              **e);

int
xcb_xkb_set_device_info_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_xkb_set_device_info_checked (xcb_connection_t                *c,
                                 xcb_xkb_device_spec_t            deviceSpec,
                                 uint8_t                          firstBtn,
                                 uint8_t                          nBtns,
                                 uint16_t                         change,
                                 uint16_t                         nDeviceLedFBs,
                                 const xcb_xkb_action_t          *btnActions,
                                 const xcb_xkb_device_led_info_t *leds);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xkb_set_device_info (xcb_connection_t                *c,
                         xcb_xkb_device_spec_t            deviceSpec,
                         uint8_t                          firstBtn,
                         uint8_t                          nBtns,
                         uint16_t                         change,
                         uint16_t                         nDeviceLedFBs,
                         const xcb_xkb_action_t          *btnActions,
                         const xcb_xkb_device_led_info_t *leds);

xcb_xkb_action_t *
xcb_xkb_set_device_info_btn_actions (const xcb_xkb_set_device_info_request_t *R);

int
xcb_xkb_set_device_info_btn_actions_length (const xcb_xkb_set_device_info_request_t *R);

xcb_xkb_action_iterator_t
xcb_xkb_set_device_info_btn_actions_iterator (const xcb_xkb_set_device_info_request_t *R);

int
xcb_xkb_set_device_info_leds_length (const xcb_xkb_set_device_info_request_t *R);

xcb_xkb_device_led_info_iterator_t
xcb_xkb_set_device_info_leds_iterator (const xcb_xkb_set_device_info_request_t *R);

int
xcb_xkb_set_debugging_flags_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xkb_set_debugging_flags_cookie_t
xcb_xkb_set_debugging_flags (xcb_connection_t        *c,
                             uint16_t                 msgLength,
                             uint32_t                 affectFlags,
                             uint32_t                 flags,
                             uint32_t                 affectCtrls,
                             uint32_t                 ctrls,
                             const xcb_xkb_string8_t *message);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_xkb_set_debugging_flags_cookie_t
xcb_xkb_set_debugging_flags_unchecked (xcb_connection_t        *c,
                                       uint16_t                 msgLength,
                                       uint32_t                 affectFlags,
                                       uint32_t                 flags,
                                       uint32_t                 affectCtrls,
                                       uint32_t                 ctrls,
                                       const xcb_xkb_string8_t *message);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xkb_set_debugging_flags_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xkb_set_debugging_flags_reply_t *
xcb_xkb_set_debugging_flags_reply (xcb_connection_t                      *c,
                                   xcb_xkb_set_debugging_flags_cookie_t   cookie  /**< */,
                                   xcb_generic_error_t                  **e);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
