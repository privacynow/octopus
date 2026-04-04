function _leadingConversationTargetToken(raw) {
    const text = String(raw || '').trim();
    if (!text.startsWith('@')) return '';
    const token = text.split(/\s+/, 1)[0] || '';
    return token.trim();
}

function _replaceLeadingConversationSelector(raw, selectorLabel) {
    const text = String(raw || '').trimStart();
    const token = _leadingConversationTargetToken(text);
    if (!token) return selectorLabel + ' ';
    const remainder = text.slice(token.length).trimStart();
    return selectorLabel + (remainder ? ` ${remainder}` : ' ');
}
