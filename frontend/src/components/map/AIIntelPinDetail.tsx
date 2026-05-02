'use client';

/**
 * AIIntelPinDetail — floating popup shown when the user clicks an AI Intel pin
 * on the map.
 *
 * Features:
 *   - Shows label, category, coordinates, reverse-geocoded place
 *   - Shows entity attachment info (if pin is tracking a moving object)
 *   - Editable label / description
 *   - Threaded comment system with reply support (user + agent)
 *   - Follows the Threat-alert marker pattern: offset from target with a
 *     dashed connecting line + arrow pointing at the pin.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Marker } from 'react-map-gl/maplibre';
import { API_BASE } from '@/lib/api';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import {
  fetchAIIntelPin,
  updateAIIntelPin,
  addAIIntelPinComment,
  deleteAIIntelPinComment,
} from '@/lib/aiIntelClient';
import {
  PIN_CATEGORY_COLORS,
  PIN_CATEGORY_LABELS,
  type PinCategory,
  type AIIntelPin,
  type AIIntelPinComment,
} from '@/types/aiIntel';

interface Props {
  pinId: string;
  onClose: () => void;
  onDeleted?: () => void;
  onUpdated?: () => void;
}

interface ReverseGeocode {
  city?: string;
  state?: string;
  country?: string;
  display_name?: string;
}

const POPUP_OFFSET = 160;

export const AIIntelPinDetail: React.FC<Props> = ({ pinId, onClose, onDeleted, onUpdated }) => {
  const [pin, setPin] = useState<AIIntelPin | null>(null);
  const [geo, setGeo] = useState<ReverseGeocode | null>(null);
  const [editing, setEditing] = useState(false);
  const [editLabel, setEditLabel] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editCategory, setEditCategory] = useState<PinCategory>('custom');
  const [saving, setSaving] = useState(false);

  const [newComment, setNewComment] = useState('');
  const [replyTo, setReplyTo] = useState<string>('');
  const [commentAuthor, setCommentAuthor] = useState<'user' | 'agent'>('user');
  const [posting, setPosting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const commentInputRef = useRef<HTMLTextAreaElement | null>(null);

  // Initial pin fetch
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchAIIntelPin(pinId);
        if (cancelled) return;
        setPin(res.pin);
        setEditLabel(res.pin.label);
        setEditDescription(res.pin.description || '');
        setEditCategory(res.pin.category);
      } catch (err) {
        console.error('Failed to load pin:', err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pinId]);

  // Reverse geocode once we have coordinates
  useEffect(() => {
    if (!pin) return;
    let cancelled = false;
    (async () => {
      try {
        const url = `${API_BASE}/api/geocode/reverse?lat=${pin.lat}&lng=${pin.lng}`;
        const resp = await fetch(url);
        if (!resp.ok) return;
        const data = await resp.json();
        if (cancelled) return;
        setGeo({
          city: data.city || data.town || data.village || data.hamlet || '',
          state: data.state || data.region || '',
          country: data.country || '',
          display_name: data.display_name || '',
        });
      } catch {
        /* ignore reverse geocode failures */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pin]);

  const handleSaveEdit = useCallback(async () => {
    if (!pin || !editLabel.trim()) return;
    setSaving(true);
    try {
      const res = await updateAIIntelPin(pin.id, {
        label: editLabel.trim(),
        description: editDescription.trim(),
        category: editCategory,
      });
      setPin(res.pin);
      setEditing(false);
      onUpdated?.();
    } catch (err) {
      console.error('Failed to update pin:', err);
    }
    setSaving(false);
  }, [pin, editLabel, editDescription, editCategory, onUpdated]);

  const handlePostComment = useCallback(async () => {
    if (!pin || !newComment.trim()) return;
    setPosting(true);
    try {
      const res = await addAIIntelPinComment(pin.id, {
        text: newComment.trim(),
        author: commentAuthor,
        reply_to: replyTo,
      });
      setPin(res.pin);
      setNewComment('');
      setReplyTo('');
      onUpdated?.();
    } catch (err) {
      console.error('Failed to post comment:', err);
    }
    setPosting(false);
  }, [pin, newComment, commentAuthor, replyTo, onUpdated]);

  const handleDeleteComment = useCallback(
    async (commentId: string) => {
      if (!pin) return;
      try {
        await deleteAIIntelPinComment(pin.id, commentId);
        // Refresh pin
        const refreshed = await fetchAIIntelPin(pin.id);
        setPin(refreshed.pin);
        onUpdated?.();
      } catch (err) {
        console.error('Failed to delete comment:', err);
      }
    },
    [pin, onUpdated],
  );

  const executeDeletePin = useCallback(async () => {
    if (!pin) return;
    setShowDeleteConfirm(false);
    try {
      await fetch(`${API_BASE}/api/ai/pins/${pin.id}`, { method: 'DELETE' });
      onDeleted?.();
      onClose();
    } catch (err) {
      console.error('Failed to delete pin:', err);
    }
  }, [pin, onDeleted, onClose]);

  // Stop keyboard events from leaking to global hotkeys
  const stopKeys = useCallback((e: React.KeyboardEvent) => {
    e.stopPropagation();
    e.nativeEvent.stopImmediatePropagation();
  }, []);

  if (!pin) return null;

  const categoryColor = PIN_CATEGORY_COLORS[pin.category] || '#8b5cf6';
  const locationLine = [geo?.city, geo?.state, geo?.country].filter(Boolean).join(', ');

  // Build reply map (comment_id → replies)
  const comments = pin.comments || [];
  const topLevel = comments.filter((c) => !c.reply_to);
  const replies: Record<string, AIIntelPinComment[]> = {};
  for (const c of comments) {
    if (c.reply_to) {
      (replies[c.reply_to] = replies[c.reply_to] || []).push(c);
    }
  }

  return (
    <>
    <Marker
      latitude={pin.lat}
      longitude={pin.lng}
      anchor="center"
      offset={[0, -POPUP_OFFSET]}
      style={{ zIndex: 9995 }}
    >
      <div
        className="relative"
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={stopKeys}
        onKeyUp={stopKeys}
      >
        {/* Dashed connecting line */}
        <svg
          className="absolute pointer-events-none"
          style={{ left: '50%', top: '50%', width: 1, height: 1, overflow: 'visible', zIndex: -1 }}
        >
          <line
            x1={0}
            y1={0}
            x2={0}
            y2={POPUP_OFFSET}
            stroke={categoryColor}
            strokeWidth={1.5}
            strokeDasharray="4,3"
            className="opacity-80"
          />
          <circle cx={0} cy={POPUP_OFFSET} r={4} fill={categoryColor} stroke="#0a0a14" strokeWidth={1.5} />
        </svg>

        {/* Arrow pointing down */}
        <div
          style={{
            position: 'absolute',
            bottom: -6,
            left: '50%',
            transform: 'translateX(-50%)',
            width: 0,
            height: 0,
            borderLeft: '6px solid transparent',
            borderRight: '6px solid transparent',
            borderTop: `6px solid ${categoryColor}`,
          }}
        />

        {/* Dialog body */}
        <div
          className="bg-[#0a0a14] border-2 font-mono text-white"
          style={{
            borderColor: `${categoryColor}99`,
            minWidth: 320,
            maxWidth: 360,
            maxHeight: 460,
            overflowY: 'auto',
            transform: 'translateX(-50%)',
            marginLeft: '50%',
            boxShadow: `0 10px 30px rgba(0,0,0,0.7), 0 0 0 1px ${categoryColor}33`,
          }}
        >
          {/* Header */}
          <div
            className="flex items-center justify-between px-3 py-2 border-b"
            style={{ borderColor: `${categoryColor}55`, background: `${categoryColor}18` }}
          >
            <div className="flex items-center gap-2 min-w-0">
              <span
                className="inline-block w-2 h-2 rounded-full flex-shrink-0"
                style={{ background: categoryColor }}
              />
              <span className="text-[10px] uppercase tracking-widest truncate" style={{ color: categoryColor }}>
                {PIN_CATEGORY_LABELS[pin.category] || pin.category}
              </span>
            </div>
            <div className="flex items-center gap-1">
              {!editing && (
                <button
                  type="button"
                  onClick={() => setEditing(true)}
                  className="text-[10px] px-2 py-0.5 text-violet-300 hover:text-white border border-violet-500/30 hover:border-violet-500/60"
                >
                  EDIT
                </button>
              )}
              <button
                type="button"
                onClick={() => setShowDeleteConfirm(true)}
                className="text-[10px] px-2 py-0.5 text-red-400 hover:text-red-200 border border-red-500/30 hover:border-red-500/60"
              >
                DEL
              </button>
              <button
                type="button"
                onClick={onClose}
                className="text-gray-500 hover:text-white text-base leading-none px-1"
                aria-label="Close"
              >
                ×
              </button>
            </div>
          </div>

          {/* Main body */}
          <div className="px-3 py-2 space-y-2">
            {editing ? (
              <>
                <input
                  type="text"
                  value={editLabel}
                  onChange={(e) => setEditLabel(e.target.value)}
                  placeholder="Label"
                  onMouseDown={(e) => {
                    e.stopPropagation();
                    (e.currentTarget as HTMLInputElement).focus();
                  }}
                  onKeyDown={stopKeys}
                  className="w-full px-2 py-1 text-[12px] font-mono bg-black/60 border border-violet-500/40 outline-none focus:border-violet-500"
                />
                <select
                  aria-label="Category"
                  value={editCategory}
                  onChange={(e) => setEditCategory(e.target.value as PinCategory)}
                  className="w-full px-2 py-1 text-[11px] font-mono bg-black/60 border border-violet-500/40 outline-none focus:border-violet-500 border-l-4"
                  style={{ borderLeftColor: PIN_CATEGORY_COLORS[editCategory] }}
                >
                  {(Object.keys(PIN_CATEGORY_LABELS) as PinCategory[]).map((c) => (
                    <option key={c} value={c} className="bg-[#0a0a14]">
                      {PIN_CATEGORY_LABELS[c]}
                    </option>
                  ))}
                </select>
                <textarea
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  placeholder="Notes"
                  rows={3}
                  onMouseDown={(e) => {
                    e.stopPropagation();
                    (e.currentTarget as HTMLTextAreaElement).focus();
                  }}
                  onKeyDown={stopKeys}
                  className="w-full px-2 py-1 text-[11px] font-mono bg-black/60 border border-violet-500/30 outline-none focus:border-violet-500 resize-none"
                />
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    disabled={saving || !editLabel.trim()}
                    onClick={handleSaveEdit}
                    className="flex-1 py-1 text-[11px] bg-violet-600/40 border border-violet-500/60 hover:bg-violet-600/60 disabled:opacity-40"
                  >
                    {saving ? '...' : 'SAVE'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setEditing(false);
                      setEditLabel(pin.label);
                      setEditDescription(pin.description || '');
                      setEditCategory(pin.category);
                    }}
                    className="px-3 py-1 text-[11px] border border-gray-600/40 text-gray-400 hover:text-white"
                  >
                    CANCEL
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="text-[14px] font-bold leading-snug break-words">{pin.label}</div>
                {pin.description && (
                  <div className="text-[11px] text-gray-300 whitespace-pre-wrap break-words leading-relaxed">
                    {pin.description}
                  </div>
                )}
              </>
            )}

            {/* Location / entity metadata */}
            <div className="text-[10px] text-gray-400 space-y-0.5 pt-1 border-t border-white/5">
              {pin.entity_attachment ? (
                <div className="text-cyan-400">
                  <span className="text-gray-500">TRACKING: </span>
                  {pin.entity_attachment.entity_label || pin.entity_attachment.entity_id}
                  <span className="text-cyan-600 ml-1">({pin.entity_attachment.entity_type})</span>
                </div>
              ) : null}
              <div>
                <span className="text-gray-500">COORDS: </span>
                {pin.lat.toFixed(5)}, {pin.lng.toFixed(5)}
              </div>
              {locationLine && (
                <div>
                  <span className="text-gray-500">PLACE: </span>
                  {locationLine}
                </div>
              )}
              {pin.source && (
                <div>
                  <span className="text-gray-500">SOURCE: </span>
                  {pin.source}
                </div>
              )}
            </div>
          </div>

          {/* Comments thread */}
          <div className="border-t border-white/10 px-3 py-2">
            <div className="text-[10px] uppercase tracking-widest text-violet-400 mb-1.5">
              Comments ({comments.length})
            </div>

            {topLevel.length === 0 && (
              <div className="text-[10px] text-gray-600 italic mb-1.5">No comments yet.</div>
            )}

            <div className="space-y-1.5 max-h-40 overflow-y-auto">
              {topLevel.map((c) => (
                <CommentBlock
                  key={c.id}
                  comment={c}
                  replies={replies[c.id] || []}
                  onReply={(id) => {
                    setReplyTo(id);
                    setTimeout(() => commentInputRef.current?.focus(), 30);
                  }}
                  onDelete={handleDeleteComment}
                />
              ))}
            </div>

            {/* New comment input */}
            <div className="mt-2 pt-2 border-t border-white/5 space-y-1.5">
              {replyTo && (
                <div className="text-[9px] text-violet-400 flex items-center justify-between">
                  <span>Replying to comment…</span>
                  <button
                    type="button"
                    onClick={() => setReplyTo('')}
                    className="text-gray-500 hover:text-white"
                  >
                    cancel
                  </button>
                </div>
              )}
              <textarea
                ref={commentInputRef}
                value={newComment}
                onChange={(e) => setNewComment(e.target.value)}
                placeholder={replyTo ? 'Reply…' : 'Add a comment…'}
                rows={2}
                onMouseDown={(e) => {
                  e.stopPropagation();
                  (e.currentTarget as HTMLTextAreaElement).focus();
                }}
                onKeyDown={(e) => {
                  stopKeys(e);
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    handlePostComment();
                  }
                }}
                className="w-full px-2 py-1 text-[11px] font-mono bg-black/60 border border-violet-500/30 outline-none focus:border-violet-500 resize-none"
              />
              <div className="flex items-center justify-between gap-1.5">
                <select
                  aria-label="Comment as"
                  value={commentAuthor}
                  onChange={(e) => setCommentAuthor(e.target.value as 'user' | 'agent')}
                  className="text-[10px] font-mono bg-black/60 border border-violet-500/30 px-1 py-0.5 outline-none"
                >
                  <option value="user">as USER</option>
                  <option value="agent">as AGENT</option>
                </select>
                <button
                  type="button"
                  disabled={posting || !newComment.trim()}
                  onClick={handlePostComment}
                  className="flex-1 py-1 text-[11px] bg-violet-600/40 border border-violet-500/60 hover:bg-violet-600/60 disabled:opacity-40"
                >
                  {posting ? '...' : replyTo ? 'REPLY' : 'POST'}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Marker>
    {showDeleteConfirm && (
      <ConfirmDialog
        open
        title="DELETE PIN"
        message={`Delete pin "${pin.label}"?\n\nThis cannot be undone.`}
        confirmLabel="DELETE"
        danger
        onConfirm={executeDeletePin}
        onCancel={() => setShowDeleteConfirm(false)}
      />
    )}
    </>
  );
};

// ---------------------------------------------------------------------------
// Comment block (recursive for replies)
// ---------------------------------------------------------------------------

interface CommentBlockProps {
  comment: AIIntelPinComment;
  replies: AIIntelPinComment[];
  onReply: (commentId: string) => void;
  onDelete: (commentId: string) => void;
}

const CommentBlock: React.FC<CommentBlockProps> = ({ comment, replies, onReply, onDelete }) => {
  const authorColor = comment.author === 'agent' ? '#22d3ee' : comment.author === 'openclaw' ? '#f59e0b' : '#a78bfa';
  const when = formatRelative(comment.created_at);

  return (
    <div className="text-[11px] leading-snug">
      <div className="flex items-start gap-1.5">
        <span
          className="text-[9px] uppercase tracking-wider font-bold flex-shrink-0 mt-0.5"
          style={{ color: authorColor }}
        >
          {comment.author}
        </span>
        <span className="text-[9px] text-gray-600 flex-shrink-0 mt-0.5">{when}</span>
        <div className="flex-1 min-w-0 flex items-start justify-between gap-1">
          <div className="whitespace-pre-wrap break-words text-gray-200 flex-1">{comment.text}</div>
          <div className="flex gap-1 flex-shrink-0">
            <button
              type="button"
              onClick={() => onReply(comment.id)}
              className="text-[9px] text-gray-500 hover:text-violet-300"
            >
              reply
            </button>
            <button
              type="button"
              onClick={() => onDelete(comment.id)}
              className="text-[9px] text-gray-600 hover:text-red-400"
            >
              ×
            </button>
          </div>
        </div>
      </div>
      {replies.length > 0 && (
        <div className="ml-4 mt-1 pl-2 border-l border-violet-500/20 space-y-1">
          {replies.map((r) => (
            <CommentBlock key={r.id} comment={r} replies={[]} onReply={onReply} onDelete={onDelete} />
          ))}
        </div>
      )}
    </div>
  );
};

function formatRelative(ts: number): string {
  const now = Date.now() / 1000;
  const diff = now - ts;
  if (diff < 60) return 'now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

export default AIIntelPinDetail;
