from rest_framework import serializers
from .models import DeliveryProof, Order
from app_accounts.models import CourierScore
from django.contrib.auth import get_user_model

User = get_user_model()


class DeliveryProofCreateSerializer(serializers.ModelSerializer):
    # Принимаем order_code и courier_id в запросе
    order_code = serializers.CharField(write_only=True)
    courier_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = DeliveryProof
        fields = ("order_code", "courier_id", "video", "uploaded_at")
        read_only_fields = ("uploaded_at",)

    def create(self, validated_data):

        order_code = validated_data.pop("order_code")
        courier_id = validated_data.pop("courier_id")

        try:
            order = Order.objects.get(order_code=order_code)
        except Order.DoesNotExist as e:
            print(f"------ e --------- >>> {e}")
            raise serializers.ValidationError(
                {"order_code": "Заказ с таким кодом не найден."}
            )

        try:
            courier = User.objects.get(chat_id=courier_id)
        except User.DoesNotExist as ee:
            print(f"------ ee --------- >>> {ee}")
            raise serializers.ValidationError({"courier_id": "Курьер не найден."})

        delivery_proof, created = DeliveryProof.objects.update_or_create(
            order=order, defaults={"courier": courier, **validated_data}
        )
        if created:
            CourierScore.objects.create(
                user=courier,
                order=order,
                points=1,
            )
        return delivery_proof
