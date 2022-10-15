from tinycss2 import parse_component_value_list

__all__ = ['parse']

SUPPORTED_PSEUDO_ELEMENTS = {
    # As per CSS Pseudo-Elements Module Level 4
    'first-line', 'first-letter', 'prefix', 'postfix', 'selection',
    'target-text', 'spelling-error', 'grammar-error', 'before', 'after',
    'marker', 'placeholder', 'file-selector-button',
    # As per CSS Generated Content for Paged Media Module
    'footnote-call', 'footnote-marker',
    # As per CSS Scoping Module Level 1
    'content', 'shadow',
}


def parse(input, namespaces=None, forgiving=False, relative=False):
    """Yield tinycss2 selectors found in given ``input``.

    :param input:
        A string, or an iterable of tinycss2 component values.

    """
    if isinstance(input, str):
        input = parse_component_value_list(input)
    tokens = TokenStream(input)
    namespaces = namespaces or {}
    try:
        yield parse_selector(tokens, namespaces, relative)
    except SelectorError as exception:
        if forgiving:
            return
        raise exception
    while 1:
        next = tokens.next()
        if next is None:
            return
        elif next == ',':
            try:
                yield parse_selector(tokens, namespaces, relative)
            except SelectorError as exception:
                if not forgiving:
                    raise exception
        else:
            if not forgiving:
                raise SelectorError(next, f'unexpected {next.type} token.')


def parse_selector(tokens, namespaces, relative=False):
    tokens.skip_whitespace_and_comment()
    if relative:
        peek = tokens.peek()
        if peek in ('>', '+', '~'):
            initial_combinator = peek.value
            tokens.next()
        else:
            initial_combinator = ' '
        tokens.skip_whitespace_and_comment()
    result, pseudo_element = parse_compound_selector(tokens, namespaces)
    while 1:
        has_whitespace = tokens.skip_whitespace()
        while tokens.skip_comment():
            has_whitespace = tokens.skip_whitespace() or has_whitespace
        selector = Selector(result, pseudo_element)
        if relative:
            selector = RelativeSelector(initial_combinator, selector)
        if pseudo_element is not None:
            return selector
        peek = tokens.peek()
        if peek is None or peek == ',':
            return selector
        elif peek in ('>', '+', '~'):
            combinator = peek.value
            tokens.next()
        elif has_whitespace:
            combinator = ' '
        else:
            return selector
        compound, pseudo_element = parse_compound_selector(tokens, namespaces)
        result = CombinedSelector(result, combinator, compound)


def parse_compound_selector(tokens, namespaces):
    type_selectors = parse_type_selector(tokens, namespaces)
    simple_selectors = type_selectors if type_selectors is not None else []
    while 1:
        simple_selector, pseudo_element = parse_simple_selector(
            tokens, namespaces)
        if pseudo_element is not None or simple_selector is None:
            break
        simple_selectors.append(simple_selector)

    if simple_selectors or (type_selectors, pseudo_element) != (None, None):
        return CompoundSelector(simple_selectors), pseudo_element

    peek = tokens.peek()
    peek_type = peek.type if peek else 'EOF'
    raise SelectorError(peek, f'expected a compound selector, got {peek_type}')


def parse_type_selector(tokens, namespaces):
    tokens.skip_whitespace()
    qualified_name = parse_qualified_name(tokens, namespaces)
    if qualified_name is None:
        return None

    simple_selectors = []
    namespace, local_name = qualified_name
    if local_name is not None:
        simple_selectors.append(LocalNameSelector(local_name))
    if namespace is not None:
        simple_selectors.append(NamespaceSelector(namespace))
    return simple_selectors


def parse_simple_selector(tokens, namespaces):
    peek = tokens.peek()
    if peek is None:
        return None, None
    if peek.type == 'hash' and peek.is_identifier:
        tokens.next()
        return IDSelector(peek.value), None
    elif peek == '.':
        tokens.next()
        next = tokens.next()
        if next is None or next.type != 'ident':
            raise SelectorError(next, f'Expected a class name, got {next}')
        return ClassSelector(next.value), None
    elif peek.type == '[] block':
        tokens.next()
        attr = parse_attribute_selector(TokenStream(peek.content), namespaces)
        return attr, None
    elif peek == ':':
        tokens.next()
        next = tokens.next()
        if next == ':':
            next = tokens.next()
            if next is None or next.type != 'ident':
                raise SelectorError(
                    next, f'Expected a pseudo-element name, got {next}')
            value = next.lower_value
            if value not in SUPPORTED_PSEUDO_ELEMENTS:
                raise SelectorError(
                    next, f'Expected a supported pseudo-element, got {value}')
            return None, value
        elif next is not None and next.type == 'ident':
            name = next.lower_value
            if name in ('before', 'after', 'first-line', 'first-letter'):
                return None, name
            else:
                return PseudoClassSelector(name), None
        elif next is not None and next.type == 'function':
            name = next.lower_name
            if name in ('is', 'where', 'not', 'has'):
                return parse_logical_combination(next, namespaces, name), None
            else:
                return (
                    FunctionalPseudoClassSelector(name, next.arguments), None)
        else:
            raise SelectorError(next, f'unexpected {next} token.')
    else:
        return None, None


def parse_logical_combination(matches_any_token, namespaces, name):
    forgiving = True
    relative = False
    if name == 'is':
        selector_class = MatchesAnySelector
    elif name == 'where':
        selector_class = SpecificityAdjustmentSelector
    elif name == 'not':
        forgiving = False
        selector_class = NegationSelector
    elif name == 'has':
        relative = True
        selector_class = RelationalSelector

    selectors = [
        selector for selector in
        parse(matches_any_token.arguments, namespaces, forgiving, relative)
        if selector.pseudo_element is None]
    return selector_class(selectors)


def parse_attribute_selector(tokens, namespaces):
    tokens.skip_whitespace()
    qualified_name = parse_qualified_name(
        tokens, namespaces, is_attribute=True)
    if qualified_name is None:
        next = tokens.next()
        raise SelectorError(next, f'expected attribute name, got {next}')
    namespace, local_name = qualified_name

    tokens.skip_whitespace()
    peek = tokens.peek()
    if peek is None:
        operator = None
        value = None
    elif peek in ('=', '~=', '|=', '^=', '$=', '*='):
        operator = peek.value
        tokens.next()
        tokens.skip_whitespace()
        next = tokens.next()
        if next is None or next.type not in ('ident', 'string'):
            next_type = 'None' if next is None else next.type
            raise SelectorError(
                next, f'expected attribute value, got {next_type}')
        value = next.value
    else:
        raise SelectorError(
            peek, f'expected attribute selector operator, got {peek}')

    tokens.skip_whitespace()
    next = tokens.next()
    if next is not None:
        raise SelectorError(next, f'expected ], got {next.type}')
    return AttributeSelector(namespace, local_name, operator, value)


def parse_qualified_name(tokens, namespaces, is_attribute=False):
    """Return ``(namespace, local)`` for given tokens.

    Can also return ``None`` for a wildcard.

    The empty string for ``namespace`` means "no namespace".

    """
    peek = tokens.peek()
    if peek is None:
        return None
    if peek.type == 'ident':
        first_ident = tokens.next()
        peek = tokens.peek()
        if peek != '|':
            namespace = '' if is_attribute else namespaces.get(None, None)
            return namespace, (first_ident.value, first_ident.lower_value)
        tokens.next()
        namespace = namespaces.get(first_ident.value)
        if namespace is None:
            raise SelectorError(
                first_ident,
                f'undefined namespace prefix: {first_ident.value}')
    elif peek == '*':
        next = tokens.next()
        peek = tokens.peek()
        if peek != '|':
            if is_attribute:
                raise SelectorError(
                    next, f'expected local name, got {next.type}')
            return namespaces.get(None, None), None
        tokens.next()
        namespace = None
    elif peek == '|':
        tokens.next()
        namespace = ''
    else:
        return None

    # If we get here, we just consumed '|' and set ``namespace``
    next = tokens.next()
    if next.type == 'ident':
        return namespace, (next.value, next.lower_value)
    elif next == '*' and not is_attribute:
        return namespace, None
    else:
        raise SelectorError(next, f'expected local name, got {next.type}')


class SelectorError(ValueError):
    """A specialized ``ValueError`` for invalid selectors."""


class TokenStream:
    def __init__(self, tokens):
        self.tokens = iter(tokens)
        self.peeked = []  # In reversed order

    def next(self):
        if self.peeked:
            return self.peeked.pop()
        else:
            return next(self.tokens, None)

    def peek(self):
        if not self.peeked:
            self.peeked.append(next(self.tokens, None))
        return self.peeked[-1]

    def skip(self, skip_types):
        found = False
        while 1:
            peek = self.peek()
            if peek is None or peek.type not in skip_types:
                break
            self.next()
            found = True
        return found

    def skip_whitespace(self):
        return self.skip(['whitespace'])

    def skip_comment(self):
        return self.skip(['comment'])

    def skip_whitespace_and_comment(self):
        return self.skip(['comment', 'whitespace'])


class Selector:
    def __init__(self, tree, pseudo_element=None):
        self.parsed_tree = tree
        self.pseudo_element = pseudo_element
        if pseudo_element is None:
            #: Tuple of 3 integers: http://www.w3.org/TR/selectors/#specificity
            self.specificity = tree.specificity
        else:
            a, b, c = tree.specificity
            self.specificity = a, b, c + 1

    def __repr__(self):
        pseudo = f'::{self.pseudo_element}' if self.pseudo_element else ''
        return f'{self.parsed_tree!r}{pseudo}'


class RelativeSelector:
    def __init__(self, combinator, selector):
        self.combinator = combinator
        self.selector = selector

    @property
    def specificity(self):
        return self.selector.specificity

    @property
    def pseudo_element(self):
        return self.selector.pseudo_element

    def __repr__(self):
        return (
            f'{self.selector!r}' if self.combinator == ' '
            else f'{self.combinator} {self.selector!r}')


class CombinedSelector:
    def __init__(self, left, combinator, right):
        #: Combined or compound selector
        self.left = left
        # One of `` `` (a single space), ``>``, ``+`` or ``~``.
        self.combinator = combinator
        #: compound selector
        self.right = right

    @property
    def specificity(self):
        a1, b1, c1 = self.left.specificity
        a2, b2, c2 = self.right.specificity
        return a1 + a2, b1 + b2, c1 + c2

    def __repr__(self):
        return f'{self.left!r}{self.combinator}{self.right!r}'


class CompoundSelector:
    def __init__(self, simple_selectors):
        self.simple_selectors = simple_selectors

    @property
    def specificity(self):
        if self.simple_selectors:
            # zip(*foo) turns [(a1, b1, c1), (a2, b2, c2), ...]
            # into [(a1, a2, ...), (b1, b2, ...), (c1, c2, ...)]
            return tuple(map(sum, zip(
                *(sel.specificity for sel in self.simple_selectors))))
        else:
            return 0, 0, 0

    def __repr__(self):
        return ''.join(map(repr, self.simple_selectors))


class LocalNameSelector:
    specificity = 0, 0, 1

    def __init__(self, local_name):
        self.local_name, self.lower_local_name = local_name

    def __repr__(self):
        return self.local_name


class NamespaceSelector:
    specificity = 0, 0, 0

    def __init__(self, namespace):
        #: The namespace URL as a string,
        #: or the empty string for elements not in any namespace.
        self.namespace = namespace

    def __repr__(self):
        if self.namespace == '':
            return '|'
        else:
            return f'{{{self.namespace}}}|'


class IDSelector:
    specificity = 1, 0, 0

    def __init__(self, ident):
        self.ident = ident

    def __repr__(self):
        return f'#{self.ident}'


class ClassSelector:
    specificity = 0, 1, 0

    def __init__(self, class_name):
        self.class_name = class_name

    def __repr__(self):
        return f'.{self.class_name}'


class AttributeSelector:
    specificity = 0, 1, 0

    def __init__(self, namespace, name, operator, value):
        self.namespace = namespace
        self.name, self.lower_name = name
        #: A string like ``=`` or ``~=``, or None for ``[attr]`` selectors
        self.operator = operator
        #: A string, or None for ``[attr]`` selectors
        self.value = value

    def __repr__(self):
        namespace = '*|' if self.namespace is None else f'{{{self.namespace}}}'
        return f'[{namespace}{self.name}{self.operator}{self.value!r}]'


class PseudoClassSelector:
    specificity = 0, 1, 0

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return ':' + self.name


class FunctionalPseudoClassSelector:
    specificity = 0, 1, 0

    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments

    def __repr__(self):
        return f':{self.name}{tuple(self.arguments)!r}'


class NegationSelector:
    def __init__(self, selector_list):
        self.selector_list = selector_list

    @property
    def specificity(self):
        if self.selector_list:
            return max(selector.specificity for selector in self.selector_list)
        else:
            return (0, 0, 0)

    def __repr__(self):
        return f':not({", ".join(repr(sel) for sel in self.selector_list)})'


class RelationalSelector:
    def __init__(self, selector_list):
        self.selector_list = selector_list

    @property
    def specificity(self):
        if self.selector_list:
            return max(selector.specificity for selector in self.selector_list)
        else:
            return (0, 0, 0)

    def __repr__(self):
        return f':has({", ".join(repr(sel) for sel in self.selector_list)})'


class MatchesAnySelector:
    def __init__(self, selector_list):
        self.selector_list = selector_list

    @property
    def specificity(self):
        if self.selector_list:
            return max(selector.specificity for selector in self.selector_list)
        else:
            return (0, 0, 0)

    def __repr__(self):
        return f':is({", ".join(repr(sel) for sel in self.selector_list)})'


class SpecificityAdjustmentSelector:
    def __init__(self, selector_list):
        self.selector_list = selector_list

    @property
    def specificity(self):
        return (0, 0, 0)

    def __repr__(self):
        return f':where({", ".join(repr(sel) for sel in self.selector_list)})'
