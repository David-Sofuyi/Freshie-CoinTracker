from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.contrib.auth import get_user_model
from market.models import WalletAccount, WalletTransaction, WalletLedgerEntry

ZERO = Decimal("0")


def get_wallet(user, currency):
    wallet, _ = WalletAccount.objects.get_or_create(user=user, currency=currency)
    return wallet


def balance(wallet):
    total = WalletLedgerEntry.objects.filter(account=wallet).aggregate(total=Sum("amount"))["total"]
    return total or ZERO


def post_deposit(user, currency, amount, reference, provider="paystack", provider_reference=""):
    amount = Decimal(str(amount))
    with transaction.atomic():
        existing = WalletTransaction.objects.select_for_update().filter(reference=reference).first()
        if existing and existing.status == "success":
            return existing, False
        wallet = get_wallet(user, currency)
        if existing:
            if existing.status != "pending" or existing.amount != amount or existing.user_id != user.pk:
                raise ValueError("Deposit reference does not match a pending wallet payment")
            tx = existing
            tx.status = "success"
            tx.provider = provider
            tx.provider_reference = provider_reference
            tx.description = "Confirmed wallet deposit"
            tx.save(update_fields=["status", "provider", "provider_reference", "description", "updated_at"])
        else:
            tx = WalletTransaction.objects.create(user=user, transaction_type="deposit", currency=currency,
                amount=amount, reference=reference, status="success", provider=provider,
                provider_reference=provider_reference, description="Confirmed wallet deposit")
        if not tx.entries.exists():
            WalletLedgerEntry.objects.create(transaction=tx, account=wallet, user=user, currency=currency, amount=amount)
            WalletLedgerEntry.objects.create(transaction=tx, currency=currency, amount=-amount)
        return tx, True


def transfer_between_users(sender, recipient_username, currency, amount, reference):
    amount = Decimal(str(amount))
    User = get_user_model()
    with transaction.atomic():
        recipient = User.objects.select_for_update().filter(username__iexact=recipient_username).first()
        if not recipient or recipient.pk == sender.pk:
            raise ValueError("A valid different recipient is required")
        source = get_wallet(sender, currency)
        destination = get_wallet(recipient, currency)
        source = WalletAccount.objects.select_for_update().get(pk=source.pk)
        destination = WalletAccount.objects.select_for_update().get(pk=destination.pk)
        if balance(source) < amount:
            raise ValueError("Insufficient wallet balance")
        tx = WalletTransaction.objects.create(user=sender, transaction_type="transfer", currency=currency,
            amount=amount, reference=reference, status="success", description=f"Transfer to {recipient.username}")
        WalletLedgerEntry.objects.create(transaction=tx, account=source, user=sender, currency=currency, amount=-amount)
        WalletLedgerEntry.objects.create(transaction=tx, account=destination, user=recipient, currency=currency, amount=amount)
        return tx


def reserve_withdrawal(user, currency, amount, reference, metadata):
    amount = Decimal(str(amount))
    with transaction.atomic():
        wallet = get_wallet(user, currency)
        wallet = WalletAccount.objects.select_for_update().get(pk=wallet.pk)
        if balance(wallet) < amount:
            raise ValueError("Insufficient wallet balance")
        tx = WalletTransaction.objects.create(user=user, transaction_type="withdrawal", currency=currency,
            amount=amount, reference=reference, status="pending", provider="paystack", provider_reference=reference, metadata=metadata,
            description="Bank withdrawal processing")
        WalletLedgerEntry.objects.create(transaction=tx, account=wallet, user=user, currency=currency, amount=-amount)
        WalletLedgerEntry.objects.create(transaction=tx, currency=currency, amount=amount)
        return tx


def finalize_withdrawal(provider_reference, success):
    with transaction.atomic():
        tx = WalletTransaction.objects.select_for_update().filter(provider_reference=provider_reference,
            transaction_type="withdrawal").first()
        if not tx or tx.status != "pending":
            return False
        if success:
            tx.status = "success"
        else:
            wallet = get_wallet(tx.user, tx.currency)
            WalletLedgerEntry.objects.create(transaction=tx, account=wallet, user=tx.user,
                currency=tx.currency, amount=tx.amount)
            WalletLedgerEntry.objects.create(transaction=tx, currency=tx.currency, amount=-tx.amount)
            tx.status = "failed"
        tx.save(update_fields=["status", "updated_at"])
        return True


def reverse_withdrawal(provider_reference):
    """Restore funds if Paystack reverses a previously completed payout."""
    with transaction.atomic():
        tx = WalletTransaction.objects.select_for_update().filter(
            provider_reference=provider_reference, transaction_type="withdrawal", status="success"
        ).first()
        if not tx:
            return False
        wallet = get_wallet(tx.user, tx.currency)
        WalletLedgerEntry.objects.create(transaction=tx, account=wallet, user=tx.user,
            currency=tx.currency, amount=tx.amount)
        WalletLedgerEntry.objects.create(transaction=tx, currency=tx.currency, amount=-tx.amount)
        tx.status = "failed"
        tx.description = "Paystack reversed the bank withdrawal; funds returned to wallet"
        tx.save(update_fields=["status", "description", "updated_at"])
        return True


def fail_deposit(reference):
    with transaction.atomic():
        tx = WalletTransaction.objects.select_for_update().filter(
            reference=reference, transaction_type="deposit", status="pending"
        ).first()
        if not tx:
            return False
        tx.status = "failed"
        tx.description = "Paystack payment failed"
        tx.save(update_fields=["status", "description", "updated_at"])
        return True
