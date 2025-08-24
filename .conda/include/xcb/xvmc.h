/*
 * This file generated automatically from xvmc.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_XvMC_API XCB XvMC API
 * @brief XvMC XCB Protocol Implementation.
 * @{
 **/

#ifndef __XVMC_H
#define __XVMC_H

#include "xcb.h"
#include "xv.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_XVMC_MAJOR_VERSION 1
#define XCB_XVMC_MINOR_VERSION 1

extern xcb_extension_t xcb_xvmc_id;

typedef uint32_t xcb_xvmc_context_t;

/**
 * @brief xcb_xvmc_context_iterator_t
 **/
typedef struct xcb_xvmc_context_iterator_t {
    xcb_xvmc_context_t *data;
    int                 rem;
    int                 index;
} xcb_xvmc_context_iterator_t;

typedef uint32_t xcb_xvmc_surface_t;

/**
 * @brief xcb_xvmc_surface_iterator_t
 **/
typedef struct xcb_xvmc_surface_iterator_t {
    xcb_xvmc_surface_t *data;
    int                 rem;
    int                 index;
} xcb_xvmc_surface_iterator_t;

typedef uint32_t xcb_xvmc_subpicture_t;

/**
 * @brief xcb_xvmc_subpicture_iterator_t
 **/
typedef struct xcb_xvmc_subpicture_iterator_t {
    xcb_xvmc_subpicture_t *data;
    int                    rem;
    int                    index;
} xcb_xvmc_subpicture_iterator_t;

/**
 * @brief xcb_xvmc_surface_info_t
 **/
typedef struct xcb_xvmc_surface_info_t {
    xcb_xvmc_surface_t id;
    uint16_t           chroma_format;
    uint16_t           pad0;
    uint16_t           max_width;
    uint16_t           max_height;
    uint16_t           subpicture_max_width;
    uint16_t           subpicture_max_height;
    uint32_t           mc_type;
    uint32_t           flags;
} xcb_xvmc_surface_info_t;

/**
 * @brief xcb_xvmc_surface_info_iterator_t
 **/
typedef struct xcb_xvmc_surface_info_iterator_t {
    xcb_xvmc_surface_info_t *data;
    int                      rem;
    int                      index;
} xcb_xvmc_surface_info_iterator_t;

/**
 * @brief xcb_xvmc_query_version_cookie_t
 **/
typedef struct xcb_xvmc_query_version_cookie_t {
    unsigned int sequence;
} xcb_xvmc_query_version_cookie_t;

/** Opcode for xcb_xvmc_query_version. */
#define XCB_XVMC_QUERY_VERSION 0

/**
 * @brief xcb_xvmc_query_version_request_t
 **/
typedef struct xcb_xvmc_query_version_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_xvmc_query_version_request_t;

/**
 * @brief xcb_xvmc_query_version_reply_t
 **/
typedef struct xcb_xvmc_query_version_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t major;
    uint32_t minor;
} xcb_xvmc_query_version_reply_t;

/**
 * @brief xcb_xvmc_list_surface_types_cookie_t
 **/
typedef struct xcb_xvmc_list_surface_types_cookie_t {
    unsigned int sequence;
} xcb_xvmc_list_surface_types_cookie_t;

/** Opcode for xcb_xvmc_list_surface_types. */
#define XCB_XVMC_LIST_SURFACE_TYPES 1

/**
 * @brief xcb_xvmc_list_surface_types_request_t
 **/
typedef struct xcb_xvmc_list_surface_types_request_t {
    uint8_t       major_opcode;
    uint8_t       minor_opcode;
    uint16_t      length;
    xcb_xv_port_t port_id;
} xcb_xvmc_list_surface_types_request_t;

/**
 * @brief xcb_xvmc_list_surface_types_reply_t
 **/
typedef struct xcb_xvmc_list_surface_types_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t num;
    uint8_t  pad1[20];
} xcb_xvmc_list_surface_types_reply_t;

/**
 * @brief xcb_xvmc_create_context_cookie_t
 **/
typedef struct xcb_xvmc_create_context_cookie_t {
    unsigned int sequence;
} xcb_xvmc_create_context_cookie_t;

/** Opcode for xcb_xvmc_create_context. */
#define XCB_XVMC_CREATE_CONTEXT 2

/**
 * @brief xcb_xvmc_create_context_request_t
 **/
typedef struct xcb_xvmc_create_context_request_t {
    uint8_t            major_opcode;
    uint8_t            minor_opcode;
    uint16_t           length;
    xcb_xvmc_context_t context_id;
    xcb_xv_port_t      port_id;
    xcb_xvmc_surface_t surface_id;
    uint16_t           width;
    uint16_t           height;
    uint32_t           flags;
} xcb_xvmc_create_context_request_t;

/**
 * @brief xcb_xvmc_create_context_reply_t
 **/
typedef struct xcb_xvmc_create_context_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t width_actual;
    uint16_t height_actual;
    uint32_t flags_return;
    uint8_t  pad1[20];
} xcb_xvmc_create_context_reply_t;

/** Opcode for xcb_xvmc_destroy_context. */
#define XCB_XVMC_DESTROY_CONTEXT 3

/**
 * @brief xcb_xvmc_destroy_context_request_t
 **/
typedef struct xcb_xvmc_destroy_context_request_t {
    uint8_t            major_opcode;
    uint8_t            minor_opcode;
    uint16_t           length;
    xcb_xvmc_context_t context_id;
} xcb_xvmc_destroy_context_request_t;

/**
 * @brief xcb_xvmc_create_surface_cookie_t
 **/
typedef struct xcb_xvmc_create_surface_cookie_t {
    unsigned int sequence;
} xcb_xvmc_create_surface_cookie_t;

/** Opcode for xcb_xvmc_create_surface. */
#define XCB_XVMC_CREATE_SURFACE 4

/**
 * @brief xcb_xvmc_create_surface_request_t
 **/
typedef struct xcb_xvmc_create_surface_request_t {
    uint8_t            major_opcode;
    uint8_t            minor_opcode;
    uint16_t           length;
    xcb_xvmc_surface_t surface_id;
    xcb_xvmc_context_t context_id;
} xcb_xvmc_create_surface_request_t;

/**
 * @brief xcb_xvmc_create_surface_reply_t
 **/
typedef struct xcb_xvmc_create_surface_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint8_t  pad1[24];
} xcb_xvmc_create_surface_reply_t;

/** Opcode for xcb_xvmc_destroy_surface. */
#define XCB_XVMC_DESTROY_SURFACE 5

/**
 * @brief xcb_xvmc_destroy_surface_request_t
 **/
typedef struct xcb_xvmc_destroy_surface_request_t {
    uint8_t            major_opcode;
    uint8_t            minor_opcode;
    uint16_t           length;
    xcb_xvmc_surface_t surface_id;
} xcb_xvmc_destroy_surface_request_t;

/**
 * @brief xcb_xvmc_create_subpicture_cookie_t
 **/
typedef struct xcb_xvmc_create_subpicture_cookie_t {
    unsigned int sequence;
} xcb_xvmc_create_subpicture_cookie_t;

/** Opcode for xcb_xvmc_create_subpicture. */
#define XCB_XVMC_CREATE_SUBPICTURE 6

/**
 * @brief xcb_xvmc_create_subpicture_request_t
 **/
typedef struct xcb_xvmc_create_subpicture_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xvmc_subpicture_t subpicture_id;
    xcb_xvmc_context_t    context;
    uint32_t              xvimage_id;
    uint16_t              width;
    uint16_t              height;
} xcb_xvmc_create_subpicture_request_t;

/**
 * @brief xcb_xvmc_create_subpicture_reply_t
 **/
typedef struct xcb_xvmc_create_subpicture_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t width_actual;
    uint16_t height_actual;
    uint16_t num_palette_entries;
    uint16_t entry_bytes;
    uint8_t  component_order[4];
    uint8_t  pad1[12];
} xcb_xvmc_create_subpicture_reply_t;

/** Opcode for xcb_xvmc_destroy_subpicture. */
#define XCB_XVMC_DESTROY_SUBPICTURE 7

/**
 * @brief xcb_xvmc_destroy_subpicture_request_t
 **/
typedef struct xcb_xvmc_destroy_subpicture_request_t {
    uint8_t               major_opcode;
    uint8_t               minor_opcode;
    uint16_t              length;
    xcb_xvmc_subpicture_t subpicture_id;
} xcb_xvmc_destroy_subpicture_request_t;

/**
 * @brief xcb_xvmc_list_subpicture_types_cookie_t
 **/
typedef struct xcb_xvmc_list_subpicture_types_cookie_t {
    unsigned int sequence;
} xcb_xvmc_list_subpicture_types_cookie_t;

/** Opcode for xcb_xvmc_list_subpicture_types. */
#define XCB_XVMC_LIST_SUBPICTURE_TYPES 8

/**
 * @brief xcb_xvmc_list_subpicture_types_request_t
 **/
typedef struct xcb_xvmc_list_subpicture_types_request_t {
    uint8_t            major_opcode;
    uint8_t            minor_opcode;
    uint16_t           length;
    xcb_xv_port_t      port_id;
    xcb_xvmc_surface_t surface_id;
} xcb_xvmc_list_subpicture_types_request_t;

/**
 * @brief xcb_xvmc_list_subpicture_types_reply_t
 **/
typedef struct xcb_xvmc_list_subpicture_types_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t num;
    uint8_t  pad1[20];
} xcb_xvmc_list_subpicture_types_reply_t;

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xvmc_context_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xvmc_context_t)
 */
void
xcb_xvmc_context_next (xcb_xvmc_context_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xvmc_context_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xvmc_context_end (xcb_xvmc_context_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xvmc_surface_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xvmc_surface_t)
 */
void
xcb_xvmc_surface_next (xcb_xvmc_surface_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xvmc_surface_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xvmc_surface_end (xcb_xvmc_surface_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xvmc_subpicture_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xvmc_subpicture_t)
 */
void
xcb_xvmc_subpicture_next (xcb_xvmc_subpicture_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xvmc_subpicture_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xvmc_subpicture_end (xcb_xvmc_subpicture_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xvmc_surface_info_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xvmc_surface_info_t)
 */
void
xcb_xvmc_surface_info_next (xcb_xvmc_surface_info_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xvmc_surface_info_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xvmc_surface_info_end (xcb_xvmc_surface_info_iterator_t i);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xvmc_query_version_cookie_t
xcb_xvmc_query_version (xcb_connection_t *c);

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
xcb_xvmc_query_version_cookie_t
xcb_xvmc_query_version_unchecked (xcb_connection_t *c);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xvmc_query_version_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xvmc_query_version_reply_t *
xcb_xvmc_query_version_reply (xcb_connection_t                 *c,
                              xcb_xvmc_query_version_cookie_t   cookie  /**< */,
                              xcb_generic_error_t             **e);

int
xcb_xvmc_list_surface_types_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xvmc_list_surface_types_cookie_t
xcb_xvmc_list_surface_types (xcb_connection_t *c,
                             xcb_xv_port_t     port_id);

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
xcb_xvmc_list_surface_types_cookie_t
xcb_xvmc_list_surface_types_unchecked (xcb_connection_t *c,
                                       xcb_xv_port_t     port_id);

xcb_xvmc_surface_info_t *
xcb_xvmc_list_surface_types_surfaces (const xcb_xvmc_list_surface_types_reply_t *R);

int
xcb_xvmc_list_surface_types_surfaces_length (const xcb_xvmc_list_surface_types_reply_t *R);

xcb_xvmc_surface_info_iterator_t
xcb_xvmc_list_surface_types_surfaces_iterator (const xcb_xvmc_list_surface_types_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xvmc_list_surface_types_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xvmc_list_surface_types_reply_t *
xcb_xvmc_list_surface_types_reply (xcb_connection_t                      *c,
                                   xcb_xvmc_list_surface_types_cookie_t   cookie  /**< */,
                                   xcb_generic_error_t                  **e);

int
xcb_xvmc_create_context_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xvmc_create_context_cookie_t
xcb_xvmc_create_context (xcb_connection_t   *c,
                         xcb_xvmc_context_t  context_id,
                         xcb_xv_port_t       port_id,
                         xcb_xvmc_surface_t  surface_id,
                         uint16_t            width,
                         uint16_t            height,
                         uint32_t            flags);

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
xcb_xvmc_create_context_cookie_t
xcb_xvmc_create_context_unchecked (xcb_connection_t   *c,
                                   xcb_xvmc_context_t  context_id,
                                   xcb_xv_port_t       port_id,
                                   xcb_xvmc_surface_t  surface_id,
                                   uint16_t            width,
                                   uint16_t            height,
                                   uint32_t            flags);

uint32_t *
xcb_xvmc_create_context_priv_data (const xcb_xvmc_create_context_reply_t *R);

int
xcb_xvmc_create_context_priv_data_length (const xcb_xvmc_create_context_reply_t *R);

xcb_generic_iterator_t
xcb_xvmc_create_context_priv_data_end (const xcb_xvmc_create_context_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xvmc_create_context_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xvmc_create_context_reply_t *
xcb_xvmc_create_context_reply (xcb_connection_t                  *c,
                               xcb_xvmc_create_context_cookie_t   cookie  /**< */,
                               xcb_generic_error_t              **e);

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
xcb_xvmc_destroy_context_checked (xcb_connection_t   *c,
                                  xcb_xvmc_context_t  context_id);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xvmc_destroy_context (xcb_connection_t   *c,
                          xcb_xvmc_context_t  context_id);

int
xcb_xvmc_create_surface_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xvmc_create_surface_cookie_t
xcb_xvmc_create_surface (xcb_connection_t   *c,
                         xcb_xvmc_surface_t  surface_id,
                         xcb_xvmc_context_t  context_id);

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
xcb_xvmc_create_surface_cookie_t
xcb_xvmc_create_surface_unchecked (xcb_connection_t   *c,
                                   xcb_xvmc_surface_t  surface_id,
                                   xcb_xvmc_context_t  context_id);

uint32_t *
xcb_xvmc_create_surface_priv_data (const xcb_xvmc_create_surface_reply_t *R);

int
xcb_xvmc_create_surface_priv_data_length (const xcb_xvmc_create_surface_reply_t *R);

xcb_generic_iterator_t
xcb_xvmc_create_surface_priv_data_end (const xcb_xvmc_create_surface_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xvmc_create_surface_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xvmc_create_surface_reply_t *
xcb_xvmc_create_surface_reply (xcb_connection_t                  *c,
                               xcb_xvmc_create_surface_cookie_t   cookie  /**< */,
                               xcb_generic_error_t              **e);

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
xcb_xvmc_destroy_surface_checked (xcb_connection_t   *c,
                                  xcb_xvmc_surface_t  surface_id);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xvmc_destroy_surface (xcb_connection_t   *c,
                          xcb_xvmc_surface_t  surface_id);

int
xcb_xvmc_create_subpicture_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xvmc_create_subpicture_cookie_t
xcb_xvmc_create_subpicture (xcb_connection_t      *c,
                            xcb_xvmc_subpicture_t  subpicture_id,
                            xcb_xvmc_context_t     context,
                            uint32_t               xvimage_id,
                            uint16_t               width,
                            uint16_t               height);

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
xcb_xvmc_create_subpicture_cookie_t
xcb_xvmc_create_subpicture_unchecked (xcb_connection_t      *c,
                                      xcb_xvmc_subpicture_t  subpicture_id,
                                      xcb_xvmc_context_t     context,
                                      uint32_t               xvimage_id,
                                      uint16_t               width,
                                      uint16_t               height);

uint32_t *
xcb_xvmc_create_subpicture_priv_data (const xcb_xvmc_create_subpicture_reply_t *R);

int
xcb_xvmc_create_subpicture_priv_data_length (const xcb_xvmc_create_subpicture_reply_t *R);

xcb_generic_iterator_t
xcb_xvmc_create_subpicture_priv_data_end (const xcb_xvmc_create_subpicture_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xvmc_create_subpicture_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xvmc_create_subpicture_reply_t *
xcb_xvmc_create_subpicture_reply (xcb_connection_t                     *c,
                                  xcb_xvmc_create_subpicture_cookie_t   cookie  /**< */,
                                  xcb_generic_error_t                 **e);

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
xcb_xvmc_destroy_subpicture_checked (xcb_connection_t      *c,
                                     xcb_xvmc_subpicture_t  subpicture_id);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xvmc_destroy_subpicture (xcb_connection_t      *c,
                             xcb_xvmc_subpicture_t  subpicture_id);

int
xcb_xvmc_list_subpicture_types_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xvmc_list_subpicture_types_cookie_t
xcb_xvmc_list_subpicture_types (xcb_connection_t   *c,
                                xcb_xv_port_t       port_id,
                                xcb_xvmc_surface_t  surface_id);

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
xcb_xvmc_list_subpicture_types_cookie_t
xcb_xvmc_list_subpicture_types_unchecked (xcb_connection_t   *c,
                                          xcb_xv_port_t       port_id,
                                          xcb_xvmc_surface_t  surface_id);

xcb_xv_image_format_info_t *
xcb_xvmc_list_subpicture_types_types (const xcb_xvmc_list_subpicture_types_reply_t *R);

int
xcb_xvmc_list_subpicture_types_types_length (const xcb_xvmc_list_subpicture_types_reply_t *R);

xcb_xv_image_format_info_iterator_t
xcb_xvmc_list_subpicture_types_types_iterator (const xcb_xvmc_list_subpicture_types_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xvmc_list_subpicture_types_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xvmc_list_subpicture_types_reply_t *
xcb_xvmc_list_subpicture_types_reply (xcb_connection_t                         *c,
                                      xcb_xvmc_list_subpicture_types_cookie_t   cookie  /**< */,
                                      xcb_generic_error_t                     **e);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
